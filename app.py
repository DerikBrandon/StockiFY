# ----------------------------------------------------
# BACKEND PYTHON - VERSÃO COM HTMX PARA MOVIMENTAÇÃO E HISTÓRICO
# ARQUIVO: app.py
# ----------------------------------------------------
from flask import Flask, render_template, request, redirect, url_for, flash, make_response # make_response adicionado
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from sqlalchemy.orm import joinedload # Para o histórico
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import io
import csv
from flask import Response

# --- Configuração Inicial ---
app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'estoque.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'uma_chave_secreta_muito_forte_aqui'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

lista_pedidos = {}

# --- MODELOS DE DADOS ---
class Produto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, default=0)

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Movimento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id', ondelete='CASCADE'), nullable=False) # Adicionado ondelete
    tipo = db.Column(db.String(10), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    produto = db.relationship('Produto', backref=db.backref('movimentos', lazy=True, cascade="all, delete-orphan")) # cascade adicionado

# --- NOVO MODELO DE DADOS: HISTÓRICO DE EDIÇÕES ---
class EditHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    produto_id = db.Column(db.Integer) # Não usar ForeignKey aqui para manter o histórico se o produto for deletado
    user_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    campo_alterado = db.Column(db.String(50), nullable=False)
    nome_produto_na_epoca = db.Column(db.String(100)) # Guarda o nome como era
    valor_antigo = db.Column(db.String(255))
    valor_novo = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    usuario = db.relationship('Usuario', backref=db.backref('edicoes_feitas', lazy=True))


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# --- ROTAS DE AUTENTICAÇÃO E CADASTRO ---
# (registrar, login, logout - sem mudanças)
@app.route('/registrar', methods=['GET', 'POST'])
def registrar():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user_exists = Usuario.query.filter_by(username=request.form['username']).first()
        if user_exists:
            flash('Este nome de usuário já existe.', 'danger')
            return redirect(url_for('registrar'))
        novo_usuario = Usuario(username=request.form['username'])
        novo_usuario.set_password(request.form['password'])
        db.session.add(novo_usuario)
        db.session.commit()
        flash('Cadastro realizado com sucesso! Faça o login.', 'success')
        return redirect(url_for('login'))
    return render_template('registrar.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Usuário ou senha inválidos.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# --- ROTAS PRINCIPAIS ---
@app.route('/')
@login_required
def root():
    return redirect(url_for('dashboard'))

# --- ROTA DO DASHBOARD (VERSÃO SIMPLES COM 2 GRÁFICOS) ---
@app.route('/dashboard')
@login_required
def dashboard():
    produtos_estoque = Produto.query.order_by(Produto.nome).all()
    labels = [p.nome for p in produtos_estoque]
    data = [p.quantidade for p in produtos_estoque]
    return render_template('dashboard.html', labels=labels, data=data)


# --- ROTAS DE PRODUTO E INVENTÁRIO ---
@app.route('/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_produto():
    if request.method == 'POST':
        try:
            nome = request.form['nome'].strip()
            quantidade = int(request.form['quantidade_inicial'])
            if quantidade < 0 or not nome: raise ValueError
            novo_produto = Produto(nome=nome, quantidade=quantidade)
            db.session.add(novo_produto)
            db.session.commit()
            if quantidade > 0:
                movimento_inicial = Movimento(produto_id=novo_produto.id, tipo='entrada', quantidade=quantidade)
                db.session.add(movimento_inicial)
                db.session.commit()
            flash(f"Produto '{nome}' adicionado!", "success")
            return redirect(url_for('inventario'))
        except (ValueError, KeyError):
            flash('Dados inválidos.', 'danger')
            return redirect(url_for('adicionar_produto'))
    return render_template('adicionar_produto.html')

@app.route('/inventario')
@login_required
def inventario():
    estoque_db = Produto.query.order_by(Produto.id).all() # Ordenar por ID pode ser melhor para consistência
    return render_template('index.html', estoque=estoque_db)

# --- ROTA HELPER PARA ATUALIZAR O TARGET DO FORM HTMX ---
@app.route('/get-product-row-target', methods=['POST'])
@login_required
def get_product_row_target():
    produto_id = request.form.get('codigo', '0').strip()
    if not produto_id.isdigit():
        produto_id = '0' # Default seguro se não for número

    target_id = f"#linha-produto-{produto_id}"
    response = make_response()
    # Usa o header HX-Retarget da extensão response-targets
    response.headers['HX-Retarget'] = target_id
    # Garante o swap correto mesmo se definido no backend
    # response.headers['HX-Reswap'] = 'outerHTML' 
    return response

# --- ROTA DE MOVIMENTAÇÃO ATUALIZADA PARA HTMX ---
@app.route('/movimentar', methods=['POST'])
@login_required
def movimentar():
    produto_id_str = request.form.get('codigo', '').strip()
    produto = None
    is_htmx = 'HX-Request' in request.headers

    try:
        if not produto_id_str.isdigit():
             raise ValueError("Código do produto inválido.")
        produto_id = int(produto_id_str)
        produto = db.session.get(Produto, produto_id) # Usar db.session.get é mais eficiente
        quantidade = int(request.form['quantidade'])
        tipo = request.form['tipo_movimento']
        
        if not produto: raise ValueError(f"Produto com código {produto_id} não encontrado.")
        if quantidade <= 0: raise ValueError("Quantidade deve ser maior que zero.")

        if tipo == 'entrada':
            produto.quantidade += quantidade
        elif tipo == 'saida':
            if produto.quantidade < quantidade:
                raise ValueError(f'Estoque insuficiente para {produto.nome}. ({produto.quantidade} em estoque)')
            produto.quantidade -= quantidade
        else:
             raise ValueError("Tipo de movimento inválido.")
        
        novo_movimento = Movimento(produto_id=produto.id, tipo=tipo, quantidade=quantidade)
        db.session.add(novo_movimento)
        db.session.commit()
        
        # Flash sempre é útil, mesmo que só apareça no próximo load completo
        flash(f"Movimentação de {tipo} registrada para {produto.nome} ({quantidade} unidades).", "success")

        if is_htmx:
            # Retorna APENAS o HTML da linha da tabela atualizada
            return render_template('_linha_produto.html', produto=produto)
        else:
            return redirect(url_for('inventario'))

    except (ValueError, KeyError, TypeError) as e:
        error_message = str(e) or 'Dados inválidos para movimentação.'
        flash(error_message, 'danger') # Mostra o erro

        if is_htmx and produto:
             # Se deu erro mas o produto existe (ex: estoque insuficiente), 
             # retorna a linha como estava ANTES da tentativa de commit.
             # Precisamos recarregar o produto do DB para ter certeza do estado original
             db.session.rollback() # Desfaz qualquer mudança não commitada
             produto_atual = db.session.get(Produto, produto_id)
             # Usa um header especial para exibir o flash via JS (requer JS no frontend)
             response = make_response(render_template('_linha_produto.html', produto=produto_atual))
             response.headers['HX-Trigger'] = '{"showFlash": "true"}' # Sinaliza para mostrar flash
             return response, 422 # Código de erro (Unprocessable Entity)
        elif is_htmx:
            # Se o produto nem foi encontrado ou outro erro grave
            db.session.rollback()
            # Retorna um fragmento vazio ou uma mensagem de erro direta
            response = make_response(f"<div id='linha-produto-{produto_id_str or 0}'></div>", 404 if "não encontrado" in error_message else 400) # 404 ou 400
            response.headers['HX-Trigger'] = '{"showFlash": "true"}'
            return response
        else: # Requisição normal
            db.session.rollback()
            return redirect(url_for('inventario'))


# --- ROTA EDITAR NOME ATUALIZADA PARA SALVAR HISTÓRICO ---
@app.route('/editar_nome', methods=['POST'])
@login_required
def editar_nome():
    try:
        produto_id = int(request.form['codigo'])
        novo_nome = request.form['novo_nome'].strip()
        produto = db.session.get(Produto, produto_id) # Usar get
        
        if not produto:
            flash("Produto não encontrado.", "danger")
        elif not novo_nome:
            flash("O novo nome não pode estar vazio.", "danger")
        elif produto.nome != novo_nome:
            valor_antigo = produto.nome 
            nome_antigo_produto = produto.nome # Guarda nome para histórico

            produto.nome = novo_nome
            
            historico = EditHistory(
                produto_id=produto.id,
                user_id=current_user.id,
                campo_alterado='nome',
                nome_produto_na_epoca=nome_antigo_produto, # Salva o nome como era
                valor_antigo=valor_antigo,
                valor_novo=novo_nome
            )
            db.session.add(historico) 
            db.session.commit() 
            flash("Nome do produto atualizado com sucesso!", "success")
        else: # Novo nome é igual ao antigo
             flash("O novo nome é igual ao nome atual.", "info")

    except (ValueError, KeyError):
        flash("Erro ao processar a edição.", "danger")
        db.session.rollback() # Desfaz em caso de erro
        
    return redirect(url_for('inventario'))


@app.route('/excluir', methods=['POST'])
@login_required
def excluir_produto():
    # Esta rota pode ser removida se toda exclusão for feita via HTMX
    try:
        produto_id = int(request.form['codigo'])
        produto = db.session.get(Produto, produto_id)
        if produto:
            # Cascade deve cuidar dos movimentos se configurado corretamente
            # Movimento.query.filter_by(produto_id=produto_id).delete() # Pode não ser necessário com cascade
            
            # Registra a exclusão no histórico antes de deletar
            historico_exclusao = EditHistory(
                produto_id=produto.id,
                user_id=current_user.id,
                campo_alterado='exclusao',
                nome_produto_na_epoca=produto.nome,
                valor_antigo=produto.nome,
                valor_novo='-'
            )
            db.session.add(historico_exclusao)

            db.session.delete(produto)
            db.session.commit()
            flash(f"Produto '{produto.nome}' e seu histórico foram excluídos.", "success")
        else:
            flash("Produto não encontrado para exclusão.", "danger")
    except (ValueError, KeyError):
        flash("Erro ao tentar excluir o produto.", "danger")
        db.session.rollback()
    return redirect(url_for('inventario'))

# --- ROTA DE EXCLUSÃO PARA HTMX ATUALIZADA ---
@app.route('/excluir-produto/<int:produto_id>', methods=['POST'])
@login_required
def excluir_produto_htmx(produto_id):
    try:
        produto = db.session.get(Produto, produto_id)
        if produto:
            nome_produto_excluido = produto.nome # Guarda o nome antes de excluir
            
            # Registra a exclusão no histórico antes de deletar
            historico_exclusao = EditHistory(
                produto_id=produto.id,
                user_id=current_user.id,
                campo_alterado='exclusao',
                nome_produto_na_epoca=nome_produto_excluido,
                valor_antigo=nome_produto_excluido,
                valor_novo='-'
            )
            db.session.add(historico_exclusao)
            
            # Cascade deve cuidar da exclusão dos movimentos
            db.session.delete(produto)
            db.session.commit()
            flash(f"Produto '{nome_produto_excluido}' excluído com sucesso.", "success")
            
            # Resposta vazia indica sucesso para o HTMX remover a linha
            response = make_response("", 200)
            response.headers['HX-Trigger'] = '{"showFlash": "true"}' # Avisa para mostrar flash
            return response
        else:
             # Se o produto não existe (talvez já excluído), retorna 404
             flash("Produto não encontrado.", "warning")
             response = make_response("", 404) 
             response.headers['HX-Trigger'] = '{"showFlash": "true"}'
             return response

    except Exception as e:
        db.session.rollback() # Garante rollback em qualquer erro
        flash(f"Erro ao tentar excluir o produto: {e}", "danger")
        response = make_response("Erro no servidor", 500)
        response.headers['HX-Trigger'] = '{"showFlash": "true"}'
        return response

# --- ROTAS DA LISTA DE PEDIDOS ---
# (lista_pedidos_page, adicionar_a_lista, limpar_lista - sem mudanças)
@app.route('/lista_pedidos')
@login_required
def lista_pedidos_page():
    lista_completa = []
    for produto_id_str, quantidade_pedida in lista_pedidos.items():
        produto = Produto.query.get(int(produto_id_str))
        if produto:
            lista_completa.append({'id': produto.id, 'nome': produto.nome, 'quantidade_pedida': quantidade_pedida})
    todos_produtos = Produto.query.order_by(Produto.nome).all()
    return render_template('lista_pedidos.html', lista_itens=lista_completa, todos_produtos=todos_produtos)

@app.route('/adicionar_a_lista', methods=['POST'])
@login_required
def adicionar_a_lista():
    try:
        produto_id = request.form['produto_id']
        quantidade = int(request.form['quantidade'])
        if quantidade <= 0: raise ValueError
        if Produto.query.get(int(produto_id)):
            lista_pedidos[produto_id] = lista_pedidos.get(produto_id, 0) + quantidade
            flash(f"Item adicionado à lista.", 'success')
        else:
            flash("Produto não encontrado.", 'danger')
    except (ValueError, KeyError):
        flash("A quantidade deve ser um número inteiro positivo.", 'danger')
    return redirect(url_for('lista_pedidos_page'))

@app.route('/limpar_lista', methods=['POST'])
@login_required
def limpar_lista():
    global lista_pedidos
    lista_pedidos = {}
    flash("Lista de pedidos limpa com sucesso!", 'success')
    return redirect(url_for('lista_pedidos_page'))


# --- ROTAS DE RELATÓRIO E EXPORTAÇÃO ---
# (relatorio_menu, relatorio_entradas, relatorio_saidas, exportar_entradas, exportar_saidas - sem mudanças)
@app.route('/relatorio')
@login_required
def relatorio_menu():
    return render_template('relatorio_menu.html')

@app.route('/relatorio/entradas', methods=['GET', 'POST'])
@login_required
def relatorio_entradas():
    query = Movimento.query.filter_by(tipo='entrada')
    data_inicio_str = request.form.get('data_inicio')
    data_fim_str = request.form.get('data_fim')
    if request.method == 'POST':
        try: # Adicionar try-except para datas inválidas
            if data_inicio_str:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
                query = query.filter(Movimento.timestamp >= data_inicio)
            if data_fim_str:
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Movimento.timestamp < data_fim)
        except ValueError:
            flash("Formato de data inválido. Use AAAA-MM-DD.", "danger")
    movimentos = query.order_by(Movimento.timestamp.desc()).all()
    return render_template('relatorio_view.html', movimentos=movimentos, tipo_relatorio="Entradas", data_inicio=data_inicio_str, data_fim=data_fim_str)

@app.route('/relatorio/saidas', methods=['GET', 'POST'])
@login_required
def relatorio_saidas():
    query = Movimento.query.filter_by(tipo='saida')
    data_inicio_str = request.form.get('data_inicio')
    data_fim_str = request.form.get('data_fim')
    if request.method == 'POST':
        try: # Adicionar try-except para datas inválidas
            if data_inicio_str:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d')
                query = query.filter(Movimento.timestamp >= data_inicio)
            if data_fim_str:
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Movimento.timestamp < data_fim)
        except ValueError:
            flash("Formato de data inválido. Use AAAA-MM-DD.", "danger")
    movimentos = query.order_by(Movimento.timestamp.desc()).all()
    return render_template('relatorio_view.html', movimentos=movimentos, tipo_relatorio="Saídas", data_inicio=data_inicio_str, data_fim=data_fim_str)


@app.route('/exportar/entradas')
@login_required
def exportar_entradas():
    movimentos = Movimento.query.filter_by(tipo='entrada').order_by(Movimento.timestamp.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Hora (UTC)', 'Codigo do Produto', 'Nome do Produto', 'Quantidade'])
    for mov in movimentos:
        writer.writerow([mov.timestamp.strftime('%d/%m/%Y'), mov.timestamp.strftime('%H:%M:%S'), mov.produto.id, mov.produto.nome, mov.quantidade])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=relatorio_entradas.csv"})

@app.route('/exportar/saidas')
@login_required
def exportar_saidas():
    movimentos = Movimento.query.filter_by(tipo='saida').order_by(Movimento.timestamp.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Data', 'Hora (UTC)', 'Codigo do Produto', 'Nome do Produto', 'Quantidade'])
    for mov in movimentos:
        writer.writerow([mov.timestamp.strftime('%d/%m/%Y'), mov.timestamp.strftime('%H:%M:%S'), mov.produto.id, mov.produto.nome, mov.quantidade])
    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=relatorio_saidas.csv"})

# --- NOVA ROTA PARA VISUALIZAR HISTÓRICO ---
@app.route('/historico')
@login_required
def historico_page():
    historico_list = EditHistory.query.options(
        joinedload(EditHistory.usuario) # Carrega dados do usuário junto
    ).order_by(EditHistory.timestamp.desc()).all()
    
    return render_template('historico.html', historico=historico_list)

# --- INICIALIZAÇÃO DO APP ---
if __name__ == '__main__':
    with app.app_context():
        # Configurar SQLite para suportar Foreign Keys (importante para cascade)
        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            from sqlalchemy import event
            from sqlalchemy.engine import Engine
            @event.listens_for(Engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        db.create_all() # Cria tabelas, incluindo EditHistory
        if not Usuario.query.filter_by(username='admin').first():
            admin_user = Usuario(username='admin')
            admin_user.set_password('123')
            db.session.add(admin_user)
            db.session.commit()
            print("\n!!! ATENÇÃO: Usuário 'admin' criado! !!!\n")
    app.run(debug=True)