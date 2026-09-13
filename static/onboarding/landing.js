/* Página de vendas: o botão do plano leva a escolha ao formulário.
 *
 * O valor vai para um campo oculto, e não para a URL: um plano no
 * endereço apareceria no histórico do navegador e nos logs do servidor
 * sem servir a nada — a escolha já está no corpo do POST.
 *
 * A página funciona sem este script. Sem ele, o link continua rolando até
 * o formulário e o campo de plano vai vazio, que o servidor lê como "não
 * indicado". Nenhuma informação essencial depende daqui.
 */
(function () {
    'use strict';

    var campo = document.getElementById('nd-lead-plan');
    if (!campo) {
        return;
    }

    document.querySelectorAll('[data-nd-plan]').forEach(function (botao) {
        botao.addEventListener('click', function () {
            campo.value = botao.getAttribute('data-nd-plan') || '';
            var nome = document.getElementById('id_name');
            if (nome) {
                /* Foco depois da rolagem: o link âncora move a página, e
                 * focar antes faria o navegador rolar duas vezes, terminando
                 * numa posição que não é a do formulário. */
                window.setTimeout(function () { nome.focus({ preventScroll: true }); }, 400);
            }
        });
    });
}());
