/*
 * Os comportamentos que antes moravam em atributos `onclick` do HTML.
 *
 * Não é reorganização por gosto: a política de conteúdo (`base/csp.py`)
 * recusa script embutido, e atributo `onclick` **é** script embutido — o
 * único jeito de mantê-lo seria `script-src 'unsafe-inline'`, que desliga
 * justamente a proteção que a política existe para dar. Nonce resolve o
 * `<script>` inline; não resolve o atributo.
 *
 * O contrato é por atributo `data-nd-*`, declarado no HTML, e a ação mora
 * aqui. Cinco comportamentos, todos delegados no documento — assim valem
 * também para o que nasce depois, dentro de um modal carregado por fetch.
 */
(function () {
    'use strict';

    /* ------------------------------------------- imprimir e fechar */

    document.addEventListener('click', function (evento) {
        var alvo = evento.target.closest('[data-nd-print]');
        if (alvo) { window.print(); return; }

        alvo = evento.target.closest('[data-nd-close]');
        if (alvo) { window.close(); }
    });

    /* ----------------------------------- confirmar antes de enviar */

    /* O texto da pergunta vem do atributo, porque quem sabe o que está
     * prestes a acontecer é a tela: "arquivar todo o histórico financeiro"
     * e "desfazer este repasse" merecem perguntas diferentes. */
    document.addEventListener('submit', function (evento) {
        var form = evento.target;
        if (!form || !form.hasAttribute('data-nd-confirm')) return;
        if (!window.confirm(form.getAttribute('data-nd-confirm'))) {
            evento.preventDefault();
        }
    }, true);

    /* ------------------------- enviar o formulário ao trocar o campo */

    /* Seletor que filtra ao mudar. Sem JavaScript o `<noscript>` ao lado
     * mostra o botão, então a tela continua funcionando. */
    document.addEventListener('change', function (evento) {
        var campo = evento.target;
        if (campo && campo.hasAttribute('data-nd-autosubmit') && campo.form) {
            campo.form.submit();
        }
    });

    /* ------------------------------- retrato que não carregou some */

    /* `error` não borbulha, então a escuta é na fase de captura. O retrato
     * do paciente some e a inicial aparece no lugar: uma imagem quebrada na
     * ficha parece defeito do sistema, e a inicial parece escolha. */
    document.addEventListener('error', function (evento) {
        var img = evento.target;
        if (!img || !img.hasAttribute || !img.hasAttribute('data-nd-fallback')) return;
        var substituto = document.getElementById(img.getAttribute('data-nd-fallback'));
        img.remove();
        if (substituto) substituto.classList.remove('d-none');
    }, true);

    /* ------------------------------------------ copiar para a área */

    document.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-nd-copy]');
        if (!botao) return;
        var origem = document.getElementById(botao.getAttribute('data-nd-copy'));
        if (!origem || !navigator.clipboard) return;
        navigator.clipboard.writeText(origem.value || origem.textContent || '').then(function () {
            var antes = botao.textContent;
            botao.textContent = 'Copiado';
            window.setTimeout(function () { botao.textContent = antes; }, 2000);
        });
    });
})();
