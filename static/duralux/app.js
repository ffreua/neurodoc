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

    function initTabs() {
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-bs-toggle="tab"], [data-bs-toggle="pill"]');
            if (!trigger) return;
            event.preventDefault();
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
            if (!pane) return;
            var content = pane.parentElement;
            content.querySelectorAll(':scope > .tab-pane').forEach(function (el) {
                el.classList.remove('active', 'show');
            });
            pane.classList.add('active', 'show');
        });
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
            form.addEventListener('submit', function () {
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

    function boot() {
        initSkin();
        initSidebar();
        initPageActions();
        initDropdowns();
        initTabs();
        initCollapse();
        initAlerts();
        initTooltips();
        initCounters();
        initFullScreen();
        initBusyButtons();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
