/*
 * Aba do exame: escolha da escala e total ao vivo.
 *
 * O total é recalculado no navegador só para o médico ver o número enquanto
 * pontua — quem grava é o servidor (`exams.scoring`), e é o valor dele que
 * entra no prontuário. As duas contas seguem a mesma regra, inclusive a
 * média de itens que compartilham grupo (SARA).
 */
(function () {
    'use strict';

    var picker = document.getElementById('scale-picker');
    var forms = Array.prototype.slice.call(document.querySelectorAll('.nd-scale-form'));
    if (!forms.length) return;

    /* -------------------------------------------------- escolha da escala */

    function show(id) {
        forms.forEach(function (form) {
            form.hidden = form.id !== id;
        });
    }

    function closeAll() {
        forms.forEach(function (form) { form.hidden = true; });
        if (picker) picker.value = '';
    }

    if (picker) {
        picker.addEventListener('change', function () {
            if (picker.value) {
                show(picker.value);
                var form = document.getElementById(picker.value);
                if (form) form.scrollIntoView({ block: 'nearest' });
            } else {
                closeAll();
            }
        });
    }

    /* Nenhuma escala abre sozinha ao carregar a página.
     *
     * Antes abria a primeira que tivesse valor registrado, e o efeito era o
     * oposto do pretendido: depois de salvar, a página voltava com aquele
     * formulário de trinta campos escancarado no meio da aba do exame, como
     * se ainda houvesse algo a fazer nele. O ✓ no seletor já diz quais
     * escalas foram aplicadas, e escolher a escala reabre com os valores
     * marcados. */
    closeAll();

    /* Botão de fechar dentro de cada formulário: quem abriu para conferir um
     * escore não deveria ter de voltar ao seletor para sair. */
    document.addEventListener('click', function (event) {
        if (!event.target.closest('[data-nd-scale-close]')) return;
        closeAll();
        var panel = document.getElementById('scale-picker');
        if (panel) panel.scrollIntoView({ block: 'nearest' });
    });

    /* ------------------------------------------------------- total ao vivo */

    function bandFor(bands, total) {
        for (var i = 0; i < bands.length; i++) {
            var band = bands[i];
            if (band.min !== undefined && band.min !== null && total < band.min) continue;
            if (band.max !== undefined && band.max !== null && total > band.max) continue;
            return band.label || '';
        }
        return '';
    }

    forms.forEach(function (form) {
        var totalEl = form.querySelector('[data-nd-total]');
        var bandEl = form.querySelector('[data-nd-band]');
        if (!totalEl) return;

        var max = form.getAttribute('data-nd-max');
        var bands = [];
        try {
            bands = JSON.parse(form.getAttribute('data-nd-bands') || '[]');
        } catch (err) {
            bands = [];
        }
        var selects = Array.prototype.slice.call(form.querySelectorAll('[data-nd-scale-item]'));

        function recalc() {
            /* Agrupa pelo sufixo do nome do item: a média de lados na SARA
             * usa o mesmo agrupamento do servidor, declarado no YAML. Aqui
             * o agrupamento vem do próprio `data-nd-group` quando houver. */
            var groups = {};
            var answered = 0;
            selects.forEach(function (select) {
                if (select.value === '') return;
                var value = parseFloat(select.value);
                if (isNaN(value)) return;
                answered += 1;
                var key = select.getAttribute('data-nd-group') || select.name;
                (groups[key] = groups[key] || []).push(value);
            });

            if (!answered) {
                totalEl.textContent = '—';
                bandEl.textContent = '';
                return;
            }

            var total = 0;
            Object.keys(groups).forEach(function (key) {
                var bucket = groups[key];
                total += bucket.reduce(function (a, b) { return a + b; }, 0) / bucket.length;
            });
            total = Math.round(total * 100) / 100;

            totalEl.textContent = total + (max ? '/' + max : '');
            var complete = answered === selects.length;
            bandEl.textContent = complete
                ? bandFor(bands, total)
                : 'parcial (' + answered + '/' + selects.length + ')';
        }

        selects.forEach(function (select) {
            select.addEventListener('change', recalc);
        });
        recalc();
    });
})();
