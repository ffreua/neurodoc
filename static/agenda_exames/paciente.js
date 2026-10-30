/* Agenda de exames: escolher o paciente. A busca é a mesma da agenda médica
 * (`/app/patients/autocomplete/`); cada resultado é um link para esta mesma
 * página com o paciente na URL — o formulário reabre com os convênios dele,
 * sem JavaScript para montar a lista de coberturas. */
(function () {
    'use strict';
    var campo = document.querySelector('[data-exame-busca]');
    var lista = document.querySelector('[data-exame-resultados]');
    if (!campo || !lista) { return; }
    var espera = null;
    campo.addEventListener('input', function () {
        window.clearTimeout(espera);
        var termo = campo.value.trim();
        if (termo.length < 2) { lista.textContent = ''; return; }
        espera = window.setTimeout(function () {
            fetch('/app/patients/autocomplete/?q=' + encodeURIComponent(termo), {
                credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}
            }).then(function (r) { return r.ok ? r.json() : {results: []}; }).then(function (dados) {
                lista.textContent = '';
                (dados.results || []).forEach(function (p) {
                    var url = new URL(window.location.href);
                    url.searchParams.set('paciente', p.id);
                    var a = document.createElement('a');
                    a.href = url.pathname + url.search;
                    a.className = 'list-group-item list-group-item-action fs-13';
                    a.textContent = p.full_name + (p.record_number ? ' · prontuário ' + p.record_number : '');
                    lista.appendChild(a);
                });
                if (!lista.children.length) {
                    var vazio = document.createElement('span');
                    vazio.className = 'list-group-item fs-12 text-muted';
                    vazio.textContent = 'Nenhum paciente com esse nome.';
                    lista.appendChild(vazio);
                }
            });
        }, 250);
    });
}());
