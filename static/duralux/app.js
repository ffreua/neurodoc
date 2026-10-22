/*
 * Duralux shell behaviour for NeuroDoc.
 *
 * The design system reference (design_system/design-system.html) ships the
 * Duralux stylesheet but no JavaScript, so the interactive contracts the CSS
 * expects are implemented here in plain JavaScript: no Bootstrap bundle, no
 * jQuery, no Popper, no external request of any kind.
 *
 * Contracts implemented (all read straight from duralux.css):
 *   html.minimenu                     sidebar collapsed to 100px
 *   .nxl-navigation.mob-navigation-active + .nxl-md-overlay   mobile sidebar
 *   .hamburger.is-active              animated mobile toggler
 *   li.nxl-hasmenu.nxl-trigger        open submenu
 *   ul.nxl-submenu.nxl-menu-visible / .nxl-menu-hidden        submenu motion
 *   .dropdown-menu.show               dropdowns
 *   .tab-content > .tab-pane.active   tabs and pills
 *   .collapse.show                    collapses and accordions
 *   .tooltip                          tooltips
 */
(function () {
    'use strict';

    var html = document.documentElement;
    var STORE = {
        minimenu: 'neurodoc.sidebar.minimenu',
    };

    function read(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (err) {
            return null;
        }
    }

    function write(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (err) {
            /* private mode / blocked storage: preference simply is not kept */
        }
    }

    function reducedMotion() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    /* ------------------------------------------------------ tema (removido) */

    /* O tema escuro saiu do produto. O que resta aqui é a limpeza para quem
     * já o tinha ligado: a preferência morava no `localStorage` do
     * navegador, e apagar só o botão deixaria essa pessoa presa num tema
     * que não existe mais e sem nada na tela para desligá-lo.
     *
     * Pode ser removido quando não houver mais navegador com a chave
     * gravada — na prática, depois de um ciclo de uso da equipe. */
    function limparTemaEscuro() {
        html.classList.remove('app-skin-dark');
        document.body.classList.remove('app-skin-dark');
        try {
            window.localStorage.removeItem('neurodoc.skin');
        } catch (err) {
            /* modo privado: não havia o que apagar */
        }
    }

    /* ------------------------------------------------------------- sidebar */

    function applyMinimenu(mini) {
        html.classList.toggle('minimenu', mini);
        var miniBtn = document.getElementById('menu-mini-button');
        var expandBtn = document.getElementById('menu-expend-button');
        if (miniBtn) miniBtn.style.display = mini ? 'none' : 'block';
        if (expandBtn) expandBtn.style.display = mini ? 'block' : 'none';
    }

    function mobileOverlay(show) {
        var header = document.querySelector('.nxl-header');
        if (!header) return;
        var overlay = header.querySelector('.nxl-md-overlay');
        if (show && !overlay) {
            overlay = document.createElement('div');
            overlay.className = 'nxl-md-overlay';
            header.appendChild(overlay);
            overlay.addEventListener('click', function () {
                closeMobileNav();
            });
        } else if (!show && overlay) {
            overlay.remove();
        }
    }

    function closeMobileNav() {
        var nav = document.querySelector('.nxl-navigation');
        if (nav) nav.classList.remove('mob-navigation-active');
        document.querySelectorAll('.nxl-head-mobile-toggler .hamburger').forEach(function (el) {
            el.classList.remove('is-active');
        });
        mobileOverlay(false);
    }

    function initSidebar() {
        applyMinimenu(read(STORE.minimenu) === '1');

        ['menu-mini-button', 'menu-expend-button'].forEach(function (id) {
            var el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('click', function (event) {
                event.preventDefault();
                var mini = !html.classList.contains('minimenu');
                applyMinimenu(mini);
                write(STORE.minimenu, mini ? '1' : '0');
            });
        });

        var mobileToggler = document.getElementById('mobile-collapse');
        if (mobileToggler) {
            mobileToggler.addEventListener('click', function (event) {
                event.preventDefault();
                var nav = document.querySelector('.nxl-navigation');
                if (!nav) return;
                var open = !nav.classList.contains('mob-navigation-active');
                nav.classList.toggle('mob-navigation-active', open);
                var burger = mobileToggler.querySelector('.hamburger');
                if (burger) burger.classList.toggle('is-active', open);
                mobileOverlay(open);
            });
        }

        /* multilevel menu: .nxl-hasmenu opens its own .nxl-submenu */
        document.querySelectorAll('.nxl-navigation .nxl-hasmenu > .nxl-link').forEach(function (link) {
            link.addEventListener('click', function (event) {
                event.preventDefault();
                var item = link.parentElement;
                var submenu = item.querySelector(':scope > .nxl-submenu');
                var open = !item.classList.contains('nxl-trigger');
                var siblings = item.parentElement.querySelectorAll(':scope > .nxl-hasmenu');
                siblings.forEach(function (other) {
                    if (other === item) return;
                    other.classList.remove('nxl-trigger');
                    var otherMenu = other.querySelector(':scope > .nxl-submenu');
                    if (otherMenu) {
                        otherMenu.classList.add('nxl-menu-hidden');
                        otherMenu.classList.remove('nxl-menu-visible');
                    }
                });
                item.classList.toggle('nxl-trigger', open);
                if (submenu) {
                    submenu.classList.toggle('nxl-menu-visible', open);
                    submenu.classList.toggle('nxl-menu-hidden', !open);
                }
            });
        });

        window.addEventListener('resize', function () {
            if (window.innerWidth > 1024) closeMobileNav();
        });
    }

    /* --------------------------------------------------- page action panel */

    /* Below 768px the theme parks .page-header-right-items off-screen and
     * reveals it with .page-header-right-open. Both the opener in the page
     * header and the "back" row inside the panel toggle it. */
    function initPageActions() {
        var panel = document.querySelector('.page-header-right-items');
        if (!panel) return;
        document.querySelectorAll('[data-nd-toggle="page-actions"]').forEach(function (el) {
            function toggle(event) {
                event.preventDefault();
                var open = !panel.classList.contains('page-header-right-open');
                panel.classList.toggle('page-header-right-open', open);
                document.querySelectorAll('button[data-nd-toggle="page-actions"]').forEach(function (btn) {
                    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
                });
            }
            el.addEventListener('click', toggle);
            el.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ') toggle(event);
            });
        });
    }

    /* ----------------------------------------------------------- dropdowns */

    function closeDropdowns(except) {
        document.querySelectorAll('.dropdown-menu.show').forEach(function (menu) {
            if (except && (menu === except || menu.contains(except))) return;
            menu.classList.remove('show');
            menu.removeAttribute('data-bs-popper');
            var trigger = menu.parentElement
                ? menu.parentElement.querySelector(':scope > [data-bs-toggle="dropdown"]')
                : null;
            if (trigger) trigger.setAttribute('aria-expanded', 'false');
        });
    }

    function initDropdowns() {
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-bs-toggle="dropdown"]');
            if (trigger) {
                event.preventDefault();
                event.stopPropagation();
                var parent = trigger.parentElement;
                var menu = parent ? parent.querySelector(':scope > .dropdown-menu') : null;
                if (!menu) return;
                var open = !menu.classList.contains('show');
                closeDropdowns(open ? menu.parentElement : null);
                menu.classList.toggle('show', open);
                /* Bootstrap gates its own placement rules (including
                 * .dropdown-menu-end right-alignment and .dropup) on the
                 * attribute Popper would add. Setting it ourselves gets the
                 * documented placement with no positioning library. */
                if (open) {
                    menu.setAttribute('data-bs-popper', 'static');
                } else {
                    menu.removeAttribute('data-bs-popper');
                }
                trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
                return;
            }
            var inside = event.target.closest('.dropdown-menu');
            if (inside && inside.closest('[data-bs-auto-close="outside"], .dropdown-menu[data-bs-auto-close="outside"]')) {
                return;
            }
            if (inside) {
                var holder = inside.parentElement
                    ? inside.parentElement.querySelector(':scope > [data-bs-toggle="dropdown"]')
                    : null;
                if (holder && holder.getAttribute('data-bs-auto-close') === 'outside') return;
            }
            closeDropdowns(null);
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closeDropdowns(null);
        });
    }

    /* ---------------------------------------------------------------- tabs */

    function targetOf(trigger) {
        var selector = trigger.getAttribute('data-bs-target') || trigger.getAttribute('href');
        if (!selector || selector === '#' || selector.charAt(0) !== '#') return null;
        try {
            return document.querySelector(selector);
        } catch (err) {
            return null;
        }
    }

    function activateTab(trigger) {
        var pane = targetOf(trigger);
        var list = trigger.closest('.nav, .nav-tabs, .nav-pills');
        if (list) {
            list.querySelectorAll('.nav-link, .nav-item > a').forEach(function (el) {
                el.classList.remove('active');
                el.setAttribute('aria-selected', 'false');
            });
        }
        trigger.classList.add('active');
        trigger.setAttribute('aria-selected', 'true');
        if (!pane) return null;
        var content = pane.parentElement;
        content.querySelectorAll(':scope > .tab-pane').forEach(function (el) {
            el.classList.remove('active', 'show');
        });
        pane.classList.add('active', 'show');
        return pane;
    }

    /* Aba pelo endereço da página.
     *
     * O servidor redireciona para `.../#tab-exame` depois de salvar, e sem
     * isto a pessoa voltava sempre para a primeira aba — o formulário que ela
     * acabou de enviar sumia da tela. Também mantém o endereço em dia ao
     * trocar de aba, então recarregar a página não perde o lugar.
     */
    function tabFromHash() {
        var hash = window.location.hash;
        if (!hash || hash.length < 2) return;
        var trigger = document.querySelector(
            '[data-bs-toggle="tab"][data-bs-target="' + hash + '"], ' +
            '[data-bs-toggle="pill"][data-bs-target="' + hash + '"], ' +
            '[data-bs-toggle="tab"][href="' + hash + '"]'
        );
        if (trigger) activateTab(trigger);
    }

    function initTabs() {
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-bs-toggle="tab"], [data-bs-toggle="pill"]');
            if (!trigger) return;
            event.preventDefault();
            var pane = activateTab(trigger);
            if (pane && pane.id && window.history && window.history.replaceState) {
                /* replaceState em vez de mudar o hash: atribuir a
                 * `location.hash` faria o navegador rolar até o painel. */
                window.history.replaceState(null, '', '#' + pane.id);
            }
        });
        tabFromHash();
        window.addEventListener('hashchange', tabFromHash);
    }

    /* ------------------------------------------------------------ collapse */

    function initCollapse() {
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-bs-toggle="collapse"]');
            if (!trigger) return;
            event.preventDefault();
            var target = targetOf(trigger);
            if (!target) return;
            var open = !target.classList.contains('show');
            var parentSelector = target.getAttribute('data-bs-parent');
            if (parentSelector && open) {
                var scope = document.querySelector(parentSelector);
                if (scope) {
                    scope.querySelectorAll('.collapse.show').forEach(function (el) {
                        el.classList.remove('show');
                    });
                    scope.querySelectorAll('[data-bs-toggle="collapse"]').forEach(function (el) {
                        el.classList.add('collapsed');
                        el.setAttribute('aria-expanded', 'false');
                    });
                }
            }
            target.classList.toggle('show', open);
            trigger.classList.toggle('collapsed', !open);
            trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
    }

    /* -------------------------------------------------------------- modais */

    /* Bootstrap deixa .modal em display:none e é o JS que o mostra, adiciona
     * .show, injeta o backdrop e põe .modal-open no body — no Duralux essa
     * última classe é o que desfoca o resto da tela. */
    function openModal(modal) {
        if (!modal || modal.classList.contains('show')) return;
        /* O modal precisa ser filho do body.
         *
         * O tema desfoca `.nxl-header`, `.nxl-navigation`, `.page-header` e
         * `.nxl-container` enquanto `body.modal-open` esta ligado. Um modal
         * declarado dentro do conteudo da pagina mora em `.nxl-container`, e
         * por isso sai borrado junto com o fundo -- a tela parece quebrada e
         * o console do navegador nao diz nada, porque nada quebrou.
         *
         * `base.html` tem `{% block modals %}` fora do container justamente
         * para isso, e a correcao certa e usa-lo. Mover aqui e a rede de
         * seguranca: uma tela nova que esqueca o bloco continua funcionando,
         * em vez de reencontrar este defeito meses depois. */
        if (modal.parentNode !== document.body) {
            document.body.appendChild(modal);
        }
        var backdrop = document.createElement('div');
        backdrop.className = 'modal-backdrop fade show';
        backdrop.dataset.ndFor = modal.id || '';
        document.body.appendChild(backdrop);
        document.body.classList.add('modal-open');
        modal.style.display = 'block';
        modal.removeAttribute('aria-hidden');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('role', 'dialog');
        /* Um reflow entre display e .show para a transição do tema rodar. */
        void modal.offsetWidth;
        modal.classList.add('show');
        var focusable = modal.querySelector(
            'input:not([type="hidden"]), select, textarea, button, [href], [tabindex]:not([tabindex="-1"])'
        );
        if (focusable) focusable.focus();
        backdrop.addEventListener('click', function () {
            closeModal(modal);
        });
        /* Avisa que abriu.
         *
         * Esta casa nao usa o JavaScript do Bootstrap para modal -- usa
         * estas funcoes --, e por isso `show.bs.modal` **nunca e
         * disparado**. Uma tela que carregue conteudo ao abrir e escute o
         * evento do Bootstrap fica esperando para sempre, sem erro no
         * console: foi o que aconteceu com o grafico de evolucao, que
         * mostrava "Montando o grafico..." e nao saia dali.
         *
         * O evento proprio existe para que carregar sob demanda seja
         * possivel sem cada tela inventar o proprio gatilho. */
        modal.dispatchEvent(new CustomEvent('nd:modal-open', {bubbles: true}));
    }

    function closeModal(modal) {
        if (!modal || !modal.classList.contains('show')) return;
        modal.classList.remove('show');
        modal.setAttribute('aria-hidden', 'true');
        modal.removeAttribute('aria-modal');
        document.querySelectorAll('.modal-backdrop').forEach(function (el) {
            el.remove();
        });
        document.body.classList.remove('modal-open');
        var hide = function () {
            modal.style.display = 'none';
        };
        if (reducedMotion()) {
            hide();
        } else {
            window.setTimeout(hide, 200);
        }
        var opener = modal.dataset.ndOpener && document.getElementById(modal.dataset.ndOpener);
        if (opener) opener.focus();
        modal.dispatchEvent(new CustomEvent('nd:modal-close', {bubbles: true}));
    }

    function initModals() {
        document.addEventListener('click', function (event) {
            var opener = event.target.closest('[data-bs-toggle="modal"]');
            if (opener) {
                event.preventDefault();
                var target = targetOf(opener);
                if (target) {
                    if (opener.id) target.dataset.ndOpener = opener.id;
                    openModal(target);
                }
                return;
            }
            var closer = event.target.closest('[data-bs-dismiss="modal"]');
            if (closer) {
                event.preventDefault();
                closeModal(closer.closest('.modal'));
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Escape') return;
            var open = document.querySelector('.modal.show');
            if (open) closeModal(open);
        });

        /* Foco preso dentro do modal: sem isso o Tab sai para a página
         * desfocada atrás, que continua clicável por teclado. */
        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Tab') return;
            var modal = document.querySelector('.modal.show');
            if (!modal) return;
            var items = Array.prototype.filter.call(
                modal.querySelectorAll(
                    'input:not([type="hidden"]), select, textarea, button, [href], [tabindex]:not([tabindex="-1"])'
                ),
                function (el) { return !el.disabled && el.offsetParent !== null; }
            );
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });
    }

    /* -------------------------------------------------------------- alerts */

    function initAlerts() {
        document.addEventListener('click', function (event) {
            var btn = event.target.closest('[data-bs-dismiss="alert"]');
            if (!btn) return;
            event.preventDefault();
            var alert = btn.closest('.alert');
            if (!alert) return;
            alert.classList.remove('show');
            if (reducedMotion()) {
                alert.remove();
            } else {
                window.setTimeout(function () {
                    alert.remove();
                }, 200);
            }
        });
    }

    /* ------------------------------------------------------------ tooltips */

    function initTooltips() {
        var current = null;

        function hide() {
            if (current) {
                current.remove();
                current = null;
            }
        }

        function show(host) {
            var text = host.getAttribute('data-bs-original-title')
                || host.getAttribute('data-nd-title')
                || host.getAttribute('aria-label');
            if (!text) return;
            hide();
            var tip = document.createElement('div');
            tip.className = 'tooltip bs-tooltip-auto fade show';
            tip.setAttribute('role', 'tooltip');
            tip.setAttribute('data-popper-placement', 'top');
            tip.style.position = 'absolute';
            tip.innerHTML = '<div class="tooltip-arrow"></div><div class="tooltip-inner"></div>';
            tip.querySelector('.tooltip-inner').textContent = text;
            document.body.appendChild(tip);
            var box = host.getBoundingClientRect();
            var own = tip.getBoundingClientRect();
            var left = box.left + window.scrollX + (box.width - own.width) / 2;
            left = Math.max(4, Math.min(left, window.innerWidth - own.width - 4));
            tip.style.left = left + 'px';
            tip.style.top = box.top + window.scrollY - own.height - 8 + 'px';
            current = tip;
        }

        document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (host) {
            if (host.hasAttribute('title')) {
                host.setAttribute('data-bs-original-title', host.getAttribute('title'));
                host.removeAttribute('title');
            }
            host.addEventListener('mouseenter', function () {
                show(host);
            });
            host.addEventListener('focus', function () {
                show(host);
            });
            host.addEventListener('mouseleave', hide);
            host.addEventListener('blur', hide);
        });

        window.addEventListener('scroll', hide, true);
    }

    /* ----------------------------------------------------------- counters */

    function initCounters() {
        var nodes = document.querySelectorAll('.counter');
        if (!nodes.length) return;
        nodes.forEach(function (node) {
            var raw = (node.textContent || '').trim();
            var match = raw.match(/^(-?[\d.]+(?:,\d+)?)(.*)$/);
            if (!match) return;
            var digits = match[1];
            var suffix = match[2] || '';
            var decimals = 0;
            var normalized = digits;
            if (digits.indexOf(',') > -1) {
                decimals = digits.split(',')[1].length;
                normalized = digits.replace(/\./g, '').replace(',', '.');
            } else {
                normalized = digits.replace(/\.(?=\d{3}\b)/g, '');
            }
            var target = parseFloat(normalized);
            if (isNaN(target)) return;
            if (reducedMotion()) return;

            var format = function (value) {
                return value.toLocaleString('pt-BR', {
                    minimumFractionDigits: decimals,
                    maximumFractionDigits: decimals,
                }) + suffix;
            };

            var started = null;
            var duration = 900;
            node.textContent = format(0);
            function step(now) {
                if (started === null) started = now;
                var progress = Math.min((now - started) / duration, 1);
                var eased = 1 - Math.pow(1 - progress, 3);
                node.textContent = format(target * eased);
                if (progress < 1) {
                    window.requestAnimationFrame(step);
                } else {
                    node.textContent = format(target);
                }
            }
            window.requestAnimationFrame(step);
        });
    }

    /* ------------------------------------------------------- full screen */

    function initFullScreen() {
        document.querySelectorAll('.full-screen-switcher').forEach(function (el) {
            el.addEventListener('click', function (event) {
                event.preventDefault();
                if (document.fullscreenElement) {
                    document.exitFullscreen();
                } else if (html.requestFullscreen) {
                    html.requestFullscreen();
                }
            });
        });
    }

    /* --------------------------------------------------------- form state */

    /* A submit button marked data-nd-busy shows the Duralux spinner state
     * while the form is posting, so slow clinical saves cannot be double
     * submitted by an impatient second click. */
    function initBusyButtons() {
        document.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                /* Desabilitar o botão clicado apaga o que ele diz.
                 *
                 * Um botão de envio com `name` carrega um valor — é assim que
                 * um formulário com "Trazer" e "Descartar" diz qual dos dois
                 * foi clicado. O navegador monta os dados do formulário
                 * **depois** de disparar `submit`, e ignora campo
                 * desabilitado: desabilitar aqui faz o `name` do botão sumir
                 * do envio, e o servidor recebe um formulário sem a ação.
                 *
                 * Era o 404 ao trazer ou descartar dado do atendimento
                 * anterior: a URL casava, a view recebia `action` vazio e
                 * recusava. Como o botão some do envio antes de a requisição
                 * sair, não havia como ver isso no servidor — só o efeito.
                 *
                 * O valor é copiado para um campo oculto antes de o botão ser
                 * desabilitado, então o envio continua dizendo o que dizia. */
                /* Envio cancelado nao trava botao.
                 *
                 * O `data-nd-confirm` de `nd-inline.js` escuta em captura no
                 * documento e chama `preventDefault()` quando a pessoa
                 * responde "cancelar". Isso cancela o envio, mas **nao**
                 * impede que este listener rode: o botao ganhava o spinner e
                 * ficava desabilitado para sempre, numa tela que nao ia a
                 * lugar nenhum. A unica saida era recarregar a pagina.
                 *
                 * `defaultPrevented` cobre qualquer cancelamento, e nao so o
                 * da confirmacao -- que e o ponto: o proximo motivo para
                 * cancelar um envio nao precisa lembrar deste arquivo. */
                if (event.defaultPrevented) return;
                var submitter = event.submitter;
                if (submitter && submitter.name && !submitter.disabled) {
                    var carrier = document.createElement('input');
                    carrier.type = 'hidden';
                    carrier.name = submitter.name;
                    carrier.value = submitter.value;
                    carrier.setAttribute('data-nd-busy-carrier', '1');
                    form.appendChild(carrier);
                }
                form.querySelectorAll('[data-nd-busy]').forEach(function (btn) {
                    if (btn.dataset.ndBusyDone) return;
                    btn.dataset.ndBusyDone = '1';
                    btn.disabled = true;
                    btn.insertAdjacentHTML(
                        'afterbegin',
                        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>'
                    );
                });
            });
        });
    }

    /* ------------------------------------------------ campos que crescem */

    /* A alça de redimensionamento saiu do CSS: arrastar o canto de um campo
     * não é decisão que o prontuário deva pedir a quem está atendendo, e
     * cada caixa arrastada deixava a tela um pouco mais torta.
     *
     * Em troca, a caixa cresce com o texto. Quem escreve uma história longa
     * continua vendo o que escreveu — sem arrastar nada, e sem barra de
     * rolagem dentro do campo.
     *
     * O `rows` do formulário passa a ser a altura **mínima**: a caixa nunca
     * encolhe abaixo dele, então a proporção pensada na tela (queixa curta,
     * história longa) continua valendo com o campo vazio. */
    var GROWABLE = 'textarea.form-control, textarea.form-control-sm';

    /* **No atendimento, a caixa não cresce: rola.** Pedido do médico em
     * 2026-10-22. Ali a tela é uma sequência longa de campos, e cada
     * história que crescia empurrava o exame, as hipóteses e o plano para
     * baixo — quem voltava a um campo de cima tinha de procurá-lo. Com
     * altura fixa (o `rows` do formulário) e barra de rolagem em cada um,
     * a página mantém a forma, e o texto continua inteiro dentro do campo.
     * O resto do sistema segue crescendo: lá os campos são poucos. A
     * marca é a mesma de `clinical/atendimento.js`. */
    var ROLA_EM_VEZ_DE_CRESCER = '[data-nd-atendimento]';

    function autoGrow(area) {
        if (area.closest(ROLA_EM_VEZ_DE_CRESCER)) return;
        /* Campo dentro de aba fechada ou `<details>` recolhido mede zero.
         * Medir aí gravaria uma altura mínima errada e a caixa apareceria
         * com uma linha só quando a aba abrisse — então nada é feito até que
         * o campo esteja de fato na tela. */
        if (!area.offsetHeight && !area.dataset.ndMinHeight) return;
        if (!area.dataset.ndMinHeight) {
            area.dataset.ndMinHeight = String(area.offsetHeight);
        }
        var minimum = parseInt(area.dataset.ndMinHeight, 10) || 0;
        area.style.height = 'auto';
        area.style.height = Math.max(minimum, area.scrollHeight) + 'px';
    }

    function growVisible(root) {
        (root || document).querySelectorAll(GROWABLE).forEach(autoGrow);
    }

    function initAutoGrow() {
        growVisible();
        document.addEventListener('input', function (event) {
            if (event.target.matches(GROWABLE)) autoGrow(event.target);
        });
        /* Abrir aba, accordion ou `<details>` é a primeira vez que aqueles
         * campos têm altura para medir. */
        document.addEventListener('click', function (event) {
            if (!event.target.closest(
                '[data-bs-toggle="tab"], [data-bs-toggle="pill"], [data-bs-toggle="collapse"], summary'
            )) return;
            window.setTimeout(growVisible, 0);
        });
    }

    function boot() {
        limparTemaEscuro();
        initSidebar();
        initPageActions();
        initDropdowns();
        initTabs();
        initCollapse();
        initModals();
        initAccountModal();
        initAlerts();
        initTooltips();
        initCounters();
        initFullScreen();
        initBusyButtons();
        initConfirm();
        initAutoGrow();
        initMasks();
    }

    /* ------------------------------------------------------- Minha conta
     *
     * A rota continua sendo uma página completa para quem está sem clínica e
     * como fallback sem JavaScript. Dentro do shell, o mesmo formulário vem
     * como fragmento: assim salvar o próprio nome não desmonta a navegação nem
     * obriga a pessoa a escolher a organização outra vez. */
    function initAccountModal() {
        var opener = document.querySelector('[data-nd-account-open]');
        var modal = document.getElementById('nd-account-modal');
        var body = modal && modal.querySelector('[data-nd-account-body]');
        if (!opener || !modal || !body) return;

        function failure() {
            body.innerHTML =
                '<div class="alert alert-danger fs-13" role="alert">' +
                'Não foi possível carregar esta tela. ' +
                '<a data-nd-account-fallback>Abrir Minha conta</a>.' +
                '</div>';
            body.querySelector('[data-nd-account-fallback]').setAttribute('href', opener.href);
        }

        function replace(response) {
            return response.text().then(function (htmlText) {
                if (!response.ok && response.status !== 400) throw new Error('account request failed');
                body.innerHTML = htmlText;
                var panel = body.querySelector('[data-nd-account-panel]');
                var savedName = panel && panel.getAttribute('data-nd-account-saved-name');
                if (savedName) {
                    document.querySelectorAll('[data-nd-account-name]').forEach(function (node) {
                        node.textContent = savedName;
                    });
                }
            });
        }

        opener.addEventListener('click', function (event) {
            event.preventDefault();
            body.innerHTML = '<p class="fs-13 text-muted mb-0">Carregando…</p>';
            openModal(modal);
            window.fetch(opener.href, {
                credentials: 'same-origin',
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            }).then(replace).catch(failure);
        });

        modal.addEventListener('submit', function (event) {
            var form = event.target.closest('[data-nd-account-form]');
            if (!form) return;
            event.preventDefault();
            var data = new FormData(form);
            var button = form.querySelector('[data-nd-busy]');
            if (button) {
                button.disabled = true;
                button.insertAdjacentHTML(
                    'afterbegin',
                    '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>'
                );
            }
            window.fetch(form.action, {
                method: 'POST', credentials: 'same-origin', body: data,
                headers: {'X-Requested-With': 'XMLHttpRequest'},
            }).then(replace).catch(failure);
        });
    }


    /* -------------------------------------------------------- máscaras
     *
     * `data-nd-mask="cpf"` pontua enquanto se digita: 311.515.098-92.
     *
     * A pontuação é de apresentação — o servidor sempre reduz a dígitos
     * antes de comparar (`documents.portal.find_patient`), então a máscara
     * não muda o que chega. Ela serve a quem digita: onze dígitos corridos
     * num campo estreito não têm onde a vista se apoiar, e o erro de um
     * dígito num CPF só aparece como "não encontramos seu cadastro".
     *
     * Só formata: não valida dígito verificador, não completa e não
     * bloqueia o envio. Um campo que se recusa a aceitar o que foi
     * digitado, sem dizer o porquê, é pior que um campo sem máscara.
     *
     * `keepCaret` preserva a posição do cursor contando dígitos, e não
     * caracteres: sem isso, editar o meio do número joga o cursor para o
     * fim a cada tecla.
     */
    function digitsOnly(value) {
        return (value || '').replace(/\D/g, '');
    }

    function formatCpf(digits) {
        var d = digits.slice(0, 11);
        if (d.length <= 3) return d;
        if (d.length <= 6) return d.slice(0, 3) + '.' + d.slice(3);
        if (d.length <= 9) return d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6);
        return d.slice(0, 3) + '.' + d.slice(3, 6) + '.' + d.slice(6, 9) + '-' + d.slice(9);
    }

    var MASKS = { cpf: { format: formatCpf, maxDigits: 11 } };

    function applyMask(input, mask) {
        var before = input.value;
        var caret = input.selectionStart;
        /* Quantos dígitos existem à esquerda do cursor. É esse número que
         * se preserva; a posição em caracteres muda quando um ponto entra. */
        var digitsBeforeCaret = digitsOnly(before.slice(0, caret)).length;
        var formatted = mask.format(digitsOnly(before));
        if (formatted === before) return;
        input.value = formatted;

        var position = formatted.length;
        var seen = 0;
        for (var i = 0; i < formatted.length; i += 1) {
            if (/\d/.test(formatted[i])) {
                seen += 1;
                if (seen === digitsBeforeCaret) { position = i + 1; break; }
            }
        }
        if (digitsBeforeCaret === 0) position = 0;
        try { input.setSelectionRange(position, position); } catch (e) { /* campo sem seleção */ }
    }

    function initMasks() {
        document.querySelectorAll('[data-nd-mask]').forEach(function (input) {
            var mask = MASKS[input.getAttribute('data-nd-mask')];
            if (!mask) return;
            /* `maxlength` sairia errado com a pontuação e cortaria dígito
             * válido; o corte é feito pelo formatador. */
            input.removeAttribute('maxlength');
            applyMask(input, mask);
            input.addEventListener('input', function () { applyMask(input, mask); });
            /* Colar um CPF com pontuação diferente da nossa passa pelo
             * mesmo caminho: o evento `input` dispara depois do `paste`. */
        });
    }

    /* ------------------------------------------ confirmação de ação destrutiva
     *
     * `data-nd-confirm="pergunta"` num `<form>`: o envio para, a pergunta
     * aparece no modal único de `base.html`, e o formulário só segue se a
     * pessoa confirmar.
     *
     * Intercepta no `submit`, e não no clique do botão: formulário também é
     * enviado por Enter dentro de um campo, e um `click` perderia esse
     * caminho — que é justamente o do envio acidental.
     */
    function initConfirm() {
        var modal = document.getElementById('nd-confirm-modal');
        var texto = document.getElementById('nd-confirm-text');
        var ok = document.getElementById('nd-confirm-ok');
        if (!modal || !texto || !ok) return;
        var pendente = null;
        var submissor = null;

        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (!form.matches || !form.matches('[data-nd-confirm]')) return;
            if (form.dataset.ndConfirmed === '1') return;   /* já passou pela pergunta */
            event.preventDefault();
            pendente = form;
            /* O botão que disparou o envio carrega `name`/`value` (`acao=ligar`),
             * e `requestSubmit()` sem argumento os perde: o servidor recebia o
             * formulário sem a ação e caía no caminho padrão. Guardado aqui,
             * ele volta no reenvio abaixo. */
            submissor = event.submitter || null;
            texto.textContent = form.getAttribute('data-nd-confirm') || 'Confirmar esta ação?';
            openModal(modal);
        }, true);

        ok.addEventListener('click', function () {
            if (!pendente) return;
            var form = pendente;
            var botao = submissor;
            pendente = null;
            submissor = null;
            /* A marca impede o laço: o `requestSubmit` abaixo dispara `submit`
             * de novo, e sem ela a pergunta reapareceria para sempre. */
            form.dataset.ndConfirmed = '1';
            closeModal(modal);
            if (form.requestSubmit) {
                if (botao && botao.form === form) {
                    form.requestSubmit(botao);
                } else {
                    form.requestSubmit();
                }
            } else {
                if (botao && botao.name) {
                    var campo = document.createElement('input');
                    campo.type = 'hidden';
                    campo.name = botao.name;
                    campo.value = botao.value;
                    form.appendChild(campo);
                }
                form.submit();
            }
        });

        modal.addEventListener('nd:closed', function () { pendente = null; submissor = null; });
    }

    /* API mínima para telas que precisam abrir um modal por código — o
     * atendimento reaproveita um único modal de confirmação para dezenas de
     * grupos do roteiro, em vez de declarar um modal por grupo. */
    window.NeuroDoc = window.NeuroDoc || {};
    window.NeuroDoc.openModal = openModal;
    window.NeuroDoc.closeModal = closeModal;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
