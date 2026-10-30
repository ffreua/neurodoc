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


/* O seletor da forma de pagamento (1.30): troca o `data-periodo` da seção
 * de planos, e o CSS mostra os números daquela forma em todos os cartões.
 * A escolha fica no navegador de quem visita, para a página voltar como
 * estava — conveniência, nada além. */
(function () {
    'use strict';

    var secao = document.querySelector('.nd-planos');
    if (!secao) { return; }
    var botoes = secao.querySelectorAll('[data-nd-periodo]');
    var CHAVE = 'nd-periodo';

    function escolher(periodo) {
        secao.setAttribute('data-periodo', periodo);
        botoes.forEach(function (b) {
            b.setAttribute('aria-pressed', b.getAttribute('data-nd-periodo') === periodo ? 'true' : 'false');
        });
    }

    botoes.forEach(function (botao) {
        botao.addEventListener('click', function () {
            var periodo = botao.getAttribute('data-nd-periodo');
            escolher(periodo);
            try { window.localStorage.setItem(CHAVE, periodo); } catch (erro) { /* segue sem lembrar */ }
        });
    });
    try {
        var salvo = window.localStorage.getItem(CHAVE);
        if (salvo && secao.querySelector('[data-nd-periodo="' + salvo + '"]')) { escolher(salvo); }
    } catch (erro) { /* sem armazenamento: fica o padrão */ }
}());

/* Entrada das seções pela rolagem, e a sombra da barra de cima.
 *
 * Só o que está **abaixo** da dobra recebe a classe que esconde: o que já
 * está na tela não pisca, e sem `IntersectionObserver` (ou sem este
 * script) nada fica escondido. */
(function () {
    'use strict';

    var nav = document.querySelector('.nd-public-nav');
    if (nav) {
        var marcar = function () { nav.classList.toggle('nd-rolou', window.scrollY > 8); };
        window.addEventListener('scroll', marcar, { passive: true });
        marcar();
    }

    if (!('IntersectionObserver' in window)) { return; }
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }
    var altura = window.innerHeight || document.documentElement.clientHeight;
    var observador = new IntersectionObserver(function (entradas) {
        entradas.forEach(function (entrada) {
            if (entrada.isIntersecting) {
                entrada.target.classList.add('nd-reveal-visivel');
                entrada.target.classList.remove('nd-reveal-pendente');
                observador.unobserve(entrada.target);
            }
        });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    document.querySelectorAll('.nd-reveal').forEach(function (el) {
        if (el.getBoundingClientRect().top > altura) {
            el.classList.add('nd-reveal-pendente');
            observador.observe(el);
        }
    });
}());
