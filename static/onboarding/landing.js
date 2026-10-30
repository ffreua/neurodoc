/* Página de vendas: o botão do plano pré-seleciona o menu do formulário.
 *
 * O campo é um `<select>` visível, e não mais um campo oculto. A
 * diferença importa para este script: antes ele **era** a única forma de
 * o plano chegar ao servidor; agora ele só poupa um clique de quem veio
 * por um cartão. Quem rola a página até o formulário escolhe no menu.
 *
 * A escolha não vai para a URL de propósito: um plano no endereço
 * apareceria no histórico do navegador e nos logs do servidor sem servir
 * a nada — ela já está no corpo do POST.
 *
 * A página funciona sem este script, e agora funciona melhor sem ele do
 * que antes: o menu continua lá, preenchível à mão.
 */
(function () {
    'use strict';

    /* O `id` é o que o Django gera para o campo `plan` do formulário. */
    var campo = document.getElementById('id_plan');
    if (!campo) {
        return;
    }

    document.querySelectorAll('[data-nd-plan]').forEach(function (botao) {
        botao.addEventListener('click', function () {
            var escolhido = botao.getAttribute('data-nd-plan') || '';
            /* Só seleciona o que o menu de fato oferece: um valor que não
             * existe entre as opções deixaria o `<select>` em branco, e a
             * pessoa veria o formulário "esquecer" o que ela clicou. */
            var existe = Array.prototype.some.call(campo.options, function (opcao) {
                return opcao.value === escolhido;
            });
            if (existe) {
                campo.value = escolhido;
            }
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

/* O aviso da novidade (`base/content.py::NOVIDADE`): aparece uma vez por
 * visitante e, fechado, não volta. A chave fica no navegador de quem leu —
 * conveniência de quem visita, e não registro de nada. O armazenamento pode
 * estar bloqueado (janela anônima, cookies recusados): o aviso então
 * aparece, e fecha do mesmo jeito, só sem lembrar. */
(function () {
    'use strict';

    var aviso = document.querySelector('[data-nd-novidade]');
    if (!aviso) {
        return;
    }
    var chave = 'nd-novidade-' + aviso.getAttribute('data-nd-novidade');
    try {
        if (window.localStorage.getItem(chave)) {
            return;
        }
    } catch (erro) { /* sem armazenamento: mostra */ }

    function fechar() {
        aviso.hidden = true;
        try { window.localStorage.setItem(chave, '1'); } catch (erro) { /* segue sem lembrar */ }
    }

    aviso.querySelectorAll('[data-nd-novidade-fechar]').forEach(function (botao) {
        botao.addEventListener('click', fechar);
    });
    document.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape' && !aviso.hidden) { fechar(); }
    });
    window.setTimeout(function () { aviso.hidden = false; }, 1200);
})();

