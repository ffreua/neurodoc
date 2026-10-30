/* Busca TUSS no campo de código do procedimento da guia (1.30).
 *
 * Usa a busca de catálogo de sempre (/app/codigos/tuss/buscar/). Escolher
 * preenche código e descrição; a vigência na data do serviço é conferida no
 * servidor ao gravar. As linhas são montadas com textContent: a descrição
 * vem de um arquivo externo. */
(function () {
    var campo = document.querySelector('[data-nd-tiss-tuss]');
    var caixa = document.getElementById('tiss-tuss-resultados');
    if (!campo || !caixa) return;
    var descricao = campo.form.querySelector('[name="descricao"]');
    var timer = null;

    function fechar() { caixa.hidden = true; caixa.innerHTML = ''; }

    campo.addEventListener('input', function () {
        window.clearTimeout(timer);
        var termo = campo.value.trim();
        if (termo.length < 2) { fechar(); return; }
        timer = window.setTimeout(function () {
            fetch('/app/codigos/tuss/buscar/?q=' + encodeURIComponent(termo),
                  {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    caixa.innerHTML = '';
                    if (!data.ok) {
                        var aviso = document.createElement('div');
                        aviso.className = 'list-group-item fs-12 text-muted';
                        aviso.textContent = data.error || 'Busca indisponível.';
                        caixa.appendChild(aviso);
                        caixa.hidden = false;
                        return;
                    }
                    (data.results || []).slice(0, 20).forEach(function (item) {
                        var linha = document.createElement('button');
                        linha.type = 'button';
                        linha.className = 'list-group-item list-group-item-action fs-12';
                        linha.textContent = item.code + ' — ' + item.description +
                            (item.in_force ? '' : ' (encerrado na TUSS)');
                        linha.addEventListener('click', function () {
                            campo.value = item.code;
                            if (descricao) descricao.value = item.description.slice(0, 150);
                            fechar();
                        });
                        caixa.appendChild(linha);
                    });
                    caixa.hidden = !caixa.children.length;
                })
                .catch(fechar);
        }, 250);
    });
    document.addEventListener('click', function (e) {
        if (!caixa.contains(e.target) && e.target !== campo) fechar();
    });
})();
