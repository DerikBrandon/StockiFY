// static/js/scripts.js

function toggleEditForm(codigo, nomeAtual) {
    const row = document.getElementById(`edit-row-${codigo}`);
    const input = document.getElementById(`edit-input-${codigo}`);
    
    // Verifica se a linha está visível (usando o estilo de display)
    if (row.style.display === "table-row") {
        // Se estiver visível, esconde
        row.style.display = "none";
    } else {
        // Se não, exibe como uma linha de tabela
        row.style.display = "table-row";
        
        // Se um nome foi passado, preenche o campo de input
        if (nomeAtual) {
            input.value = nomeAtual;
        }
        // Coloca o foco no campo de input para o usuário digitar
        input.focus();
    }
}
// static/js/scripts.js

// Função para exibir formulário de edição (você já deve ter)
function toggleEditForm(produtoId, nomeAtual = '') {
    const row = document.getElementById(`row-${produtoId}`);
    const editRow = document.getElementById(`edit-row-${produtoId}`);
    const input = document.getElementById(`edit-input-${produtoId}`);

    if (editRow.style.display === 'none' || !editRow.style.display) {
        // Mostra formulário de edição
        if (input) input.value = nomeAtual; // Preenche o nome atual
        editRow.style.display = 'table-row';
        if (row) row.style.display = 'none'; // Esconde a linha normal
        if (input) input.focus(); // Foca no input
    } else {
        // Esconde formulário de edição
        editRow.style.display = 'none';
        if (row) row.style.display = 'table-row'; // Mostra a linha normal de volta
    }
}


// --- NOVO: Listener para exibir mensagens flash com HTMX ---
document.body.addEventListener('htmx:afterOnLoad', function(evt) {
    // Verifica se o servidor enviou um header HX-Trigger para mostrar flash
    if (evt.detail.xhr.getResponseHeader("HX-Trigger") && evt.detail.xhr.getResponseHeader("HX-Trigger").includes("showFlash")) {
        // Recarrega a página inteira para buscar e exibir as mensagens flash
        // Esta é a forma mais simples. Alternativas envolvem buscar só os flashes.
        window.location.reload(); 
    }
});

// Adiciona um listener para erros HTMX também (opcional)
document.body.addEventListener('htmx:responseError', function(evt) {
    // Se o servidor respondeu com erro e pediu para mostrar flash
     if (evt.detail.xhr.getResponseHeader("HX-Trigger") && evt.detail.xhr.getResponseHeader("HX-Trigger").includes("showFlash")) {
         window.location.reload(); // Recarrega para ver o flash de erro
     } else {
         // Mostra um alerta genérico se não for para mostrar flash
         alert(`Erro: ${evt.detail.xhr.statusText}`);
     }
});

// Garante que o indicador de loading seja escondido mesmo se houver erro
document.body.addEventListener('htmx:sendError', function(evt) {
    const indicator = document.getElementById('loading-indicator');
    if (indicator) {
        indicator.classList.remove('htmx-request');
    }
});
document.body.addEventListener('htmx:afterRequest', function(evt) {
     const indicator = document.getElementById('loading-indicator');
    if (indicator) {
        indicator.classList.remove('htmx-request');
    }
});