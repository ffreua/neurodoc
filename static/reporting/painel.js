/* Dashboard: os cartões aparecem conforme a rolagem chega a eles.
 *
 * Arquivo do próprio site (a CSP não aceita script inline sem nonce nem de
 * fora). O filtro que envia ao trocar é o `data-nd-autosubmit` de sempre, em
 * `nd-inline.js`. Sem este script, ou com o movimento reduzido pedido pelo
 * sistema, nada fica escondido: a classe que esconde só entra por aqui.
 */
(function () {
    'use strict';
    var reduzido = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduzido || !('IntersectionObserver' in window)) {
        return;
    }
    var raiz = document.querySelector('[data-nd-painel]');
    if (!raiz) {
        return;
    }
    raiz.classList.add('nd-painel-js');
    var observador = new IntersectionObserver(function (entradas) {
        entradas.forEach(function (entrada) {
            if (entrada.isIntersecting) {
                entrada.target.classList.add('nd-visivel');
                observador.unobserve(entrada.target);
            }
        });
    }, { rootMargin: '0px 0px -8% 0px' });
    raiz.querySelectorAll('.nd-revela').forEach(function (el) {
        observador.observe(el);
    });
}());
