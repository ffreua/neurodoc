/*
 * Autocomplete do CID-10 no formulário de hipóteses.
 *
 * Busca por código ou por descrição, porque é assim que se procura: quem
 * sabe que é G40 digita G40; quem está pensando em "epilepsia focal" digita
 * isso. Escolher um resultado preenche o código, a descrição e o vínculo com
 * o catálogo.
 *
 * O catálogo tem 14 mil códigos, então a lista vem do servidor
 * (`clinical:cid-lookup`) e não do DOM: embutir tudo na página custaria mais
 * de um megabyte numa tela que já é grande.
 *
 * A descrição continua editável depois de escolhida. O que vai para o
 * prontuário é um retrato do texto no momento do registro — se a redação do
 * CID mudar numa versão futura, o registro antigo continua dizendo o que
 * dizia.
 */
(function () {
    'use strict';

    var input = document.querySelector('[data-nd-cid-search]');
    if (!input) return;

    var form = input.closest('form');
    var url = form.getAttribute('data-cid-url');
    if (!url) return;

    var codeField = form.querySelector('[name="code_snapshot"]');
    var descriptionField = form.querySelector('[name="description_snapshot"]');
    var idField = form.querySelector('[name="diagnosis_code_id"]');

    var MIN_CHARS = 2;
    var DEBOUNCE_MS = 220;

    /* ------------------------------------------------------------ lista */

    var list = document.createElement('div');
    list.className = 'list-group position-absolute shadow-sm';
    list.style.zIndex = '1060';
    list.style.maxHeight = '18rem';
    list.style.overflowY = 'auto';
    list.style.width = '100%';
    list.hidden = true;
    list.setAttribute('role', 'listbox');

    var anchor = document.createElement('div');
    anchor.className = 'position-relative';
    input.insertAdjacentElement('afterend', anchor);
    anchor.appendChild(list);

    var status = document.createElement('div');
    status.className = 'form-text fs-11';
    status.setAttribute('role', 'status');
    anchor.insertAdjacentElement('afterend', status);

    var results = [];
    var active = -1;

    function close() {
        list.hidden = true;
        list.innerHTML = '';
        active = -1;
        input.setAttribute('aria-expanded', 'false');
    }

    function highlight() {
        Array.prototype.forEach.call(list.children, function (row, index) {
            row.classList.toggle('active', index === active);
            if (index === active) row.scrollIntoView({ block: 'nearest' });
        });
    }

    function choose(item) {
        if (codeField) codeField.value = item.code;
        if (descriptionField) descriptionField.value = item.description;
        if (idField) idField.value = item.id;
        input.value = '';
        status.textContent = 'Selecionado: ' + item.code + ' — ' + item.description;
        status.className = 'form-text fs-11 text-success';
        close();
        if (descriptionField) descriptionField.focus();
    }

    function render(items) {
        list.innerHTML = '';
        results = items;
        if (!items.length) {
            close();
            return;
        }
        items.forEach(function (item) {
            var row = document.createElement('button');
            row.type = 'button';
            row.className = 'list-group-item list-group-item-action text-start py-2';
            row.setAttribute('role', 'option');
            var code = document.createElement('span');
            code.className = 'fw-bold text-dark fs-12 me-2';
            code.textContent = item.code;
            var text = document.createElement('span');
            text.className = 'fs-12';
            text.textContent = item.description;
            row.appendChild(code);
            row.appendChild(text);
            row.addEventListener('click', function () { choose(item); });
            list.appendChild(row);
        });
        list.hidden = false;
        input.setAttribute('aria-expanded', 'true');
        active = -1;
    }

    /* ------------------------------------------------------------ busca */

    var timer = null;
    var inFlight = null;

    function search(term) {
        if (inFlight) inFlight.abort();
        var controller = new AbortController();
        inFlight = controller;
        status.textContent = 'Buscando…';
        status.className = 'form-text fs-11 text-muted';
        fetch(url + '?q=' + encodeURIComponent(term), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: controller.signal
        })
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                render(data.results || []);
                if (!(data.results || []).length) {
                    status.textContent =
                        'Nenhum código encontrado. Você ainda pode escrever a hipótese à mão abaixo.';
                    status.className = 'form-text fs-11 text-muted';
                } else {
                    status.textContent = '';
                }
            })
            .catch(function (error) {
                if (error.name === 'AbortError') return;
                /* Falha de rede não pode travar o registro: a hipótese
                 * continua podendo ser escrita à mão. */
                close();
                status.textContent =
                    'Busca no CID indisponível agora. Escreva a hipótese à mão abaixo.';
                status.className = 'form-text fs-11 text-warning';
            });
    }

    input.addEventListener('input', function () {
        var term = input.value.trim();
        window.clearTimeout(timer);
        if (term.length < MIN_CHARS) {
            close();
            status.textContent = '';
            return;
        }
        timer = window.setTimeout(function () { search(term); }, DEBOUNCE_MS);
    });

    input.addEventListener('keydown', function (event) {
        if (list.hidden) {
            if (event.key === 'ArrowDown' && input.value.trim().length >= MIN_CHARS) {
                search(input.value.trim());
                event.preventDefault();
            }
            return;
        }
        if (event.key === 'ArrowDown') {
            active = Math.min(active + 1, results.length - 1);
            highlight();
            event.preventDefault();
        } else if (event.key === 'ArrowUp') {
            active = Math.max(active - 1, 0);
            highlight();
            event.preventDefault();
        } else if (event.key === 'Enter') {
            /* Enter com item destacado escolhe o item; sem destaque, não
             * envia o formulário por acidente enquanto a lista está aberta. */
            event.preventDefault();
            if (active >= 0) choose(results[active]);
        } else if (event.key === 'Escape') {
            close();
        }
    });

    document.addEventListener('click', function (event) {
        if (!anchor.contains(event.target) && event.target !== input) close();
    });

    /* Editar a descrição à mão desfaz o vínculo com o catálogo: o texto deixa
     * de ser o do CID escolhido, e dizer que ainda é seria falso. */
    if (descriptionField && idField) {
        descriptionField.addEventListener('input', function () {
            if (!idField.value) return;
            idField.value = '';
            status.textContent = 'Descrição editada à mão; o vínculo com o código do catálogo saiu.';
            status.className = 'form-text fs-11 text-muted';
        });
    }
})();
