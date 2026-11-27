/*
 * O bloco "Instalar agora" do artigo de ajuda (`templates/help/_instalar_agora.html`).
 *
 * Carregado sem `defer`, no meio da página, de propósito: o Chrome entrega o
 * pedido de instalação (`beforeinstallprompt`) uma vez, cedo, e um script que
 * começasse a ouvir depois o perderia — o botão nunca apareceria.
 *
 * Quatro situações, uma frase cada:
 *   - aberto pelo app instalado (`display-mode: standalone`, ou o
 *     `navigator.standalone` do iPhone): diz que já está instalado;
 *   - o navegador entregou o pedido: mostra o botão, que chama o pedido;
 *   - iPhone/iPad: aponta o passo do Safari (o iOS não tem o pedido);
 *   - o resto: os passos do artigo, como sem script.
 */
(function () {
    'use strict';

    var bloco = document.querySelector('[data-nd-instalar]');
    if (!bloco) { return; }

    function so(nome) {
        ['padrao', 'pronto', 'ios', 'ja', 'feito'].forEach(function (cada) {
            var el = bloco.querySelector('[data-nd-instalar-' + cada + ']');
            if (el) { el.hidden = (cada !== nome); }
        });
    }

    var botao = bloco.querySelector('[data-nd-instalar-botao]');
    var instalado = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
        window.navigator.standalone === true;
    if (instalado) { so('ja'); return; }

    // O iPad recente se apresenta como Mac; o toque é o que o denuncia.
    var ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (ios) { so('ios'); }

    var pedido = null;
    window.addEventListener('beforeinstallprompt', function (evento) {
        evento.preventDefault();
        pedido = evento;
        so('pronto');
        if (botao) { botao.hidden = false; }
    });

    window.addEventListener('appinstalled', function () {
        pedido = null;
        so('feito');
        if (botao) { botao.hidden = true; }
    });

    if (botao) {
        botao.addEventListener('click', function () {
            if (!pedido) { return; }
            var este = pedido;
            pedido = null;
            este.prompt();
            este.userChoice.then(function (escolha) {
                if (escolha && escolha.outcome === 'accepted') {
                    so('feito');
                    botao.hidden = true;
                }
                // Recusado: o navegador só entrega um pedido novo mais tarde,
                // então o botão sai e os passos do artigo continuam valendo.
                else { so('padrao'); botao.hidden = true; }
            });
        });
    }
})();
