/* A gaveta "Dados do paciente" na ficha (2026-11-05).
 *
 * É a mesma gaveta do atendimento (`clinical/_gaveta_ficha.html`), mas não
 * o mesmo script: `clinical/atendimento.js` carrega o salvamento automático,
 * Ctrl+S e os atalhos da evolução, que na ficha não têm o que fazer. Daqui
 * só sai abrir, fechar (botão, fundo e Esc) e devolver o foco a quem abriu.
 */
(function () {
    'use strict';
    var gaveta = document.getElementById('nd-gaveta-ficha');
    var fundo = document.getElementById('nd-gaveta-fundo');
    if (!gaveta) { return; }
    var focoAntes = null;

    function abrir() {
        focoAntes = document.activeElement;
        gaveta.classList.add('is-aberta');
        gaveta.setAttribute('aria-hidden', 'false');
        if (fundo) { fundo.hidden = false; }
        var fechar = gaveta.querySelector('[data-nd-gaveta-fechar]');
        if (fechar) { fechar.focus(); }
    }

    function fechar() {
        if (!gaveta.classList.contains('is-aberta')) { return; }
        gaveta.classList.remove('is-aberta');
        gaveta.setAttribute('aria-hidden', 'true');
        if (fundo) { fundo.hidden = true; }
        if (focoAntes && document.contains(focoAntes)) { focoAntes.focus(); }
        focoAntes = null;
    }

    document.addEventListener('click', function (event) {
        if (event.target.closest('[data-nd-gaveta-abrir="nd-gaveta-ficha"]')) {
            event.preventDefault();
            if (gaveta.classList.contains('is-aberta')) { fechar(); } else { abrir(); }
            return;
        }
        if (event.target.closest('[data-nd-gaveta-fechar]') || event.target === fundo) {
            fechar();
        }
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && gaveta.classList.contains('is-aberta')) {
            event.preventDefault();
            fechar();
        }
    });
}());
