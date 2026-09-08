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
 *   html.app-skin-dark                dark skin
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
        skin: 'neurodoc.skin',
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

    /* ---------------------------------------------------------------- skin */

    function applySkin(dark) {
        html.classList.toggle('app-skin-dark', dark);
        document.body.classList.toggle('app-skin-dark', dark);
        document.querySelectorAll('.dark-light-theme .dark-button').forEach(function (el) {
            el.style.display = dark ? 'none' : '';
        });
        document.querySelectorAll('.dark-light-theme .light-button').forEach(function (el) {
            el.style.display = dark ? '' : 'none';
        });
        document.querySelectorAll('[data-nd-skin-label]').forEach(function (el) {
            el.textContent = dark ? 'Tema claro' : 'Tema escuro';
        });
    }

    function initSkin() {
        applySkin(read(STORE.skin) === 'dark');
        document.querySelectorAll('.dark-light-theme .dark-button, .dark-light-theme .light-button, [data-nd-toggle="skin"]').forEach(function (el) {
            el.addEventListener('click', function (event) {
                event.preventDefault();
                var dark = !html.classList.contains('app-skin-dark');
                applySkin(dark);
                write(STORE.skin, dark ? 'dark' : 'light');
            });
        });
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

    function autoGrow(area) {
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
        initSkin();
        initSidebar();
        initPageActions();
        initDropdowns();
        initTabs();
        initCollapse();
        initModals();
        initAlerts();
        initTooltips();
        initCounters();
        initFullScreen();
        initBusyButtons();
        initAutoGrow();
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
