/* Busca de códigos: CID-10 (local) e TUSS (API da ANS).
 *
 * As duas abas usam o mesmo motor, com parâmetros diferentes. O que muda
 * entre elas não é a mecânica — é a origem, e por isso o TUSS espera mais
 * antes de consultar: cada tecla vira uma chamada a um serviço de
 * terceiro, e digitar "eletroencefalograma" são dezoito.
 */
(function () {
    'use strict';

    /* Escapa para texto **e** para atributo.
     *
     * A forma curta -- `div.textContent = t; return div.innerHTML` --
     * escapa `&`, `<` e `>` e **nao** escapa aspas: a serializacao de
     * um no de texto nao sabe em que contexto o resultado sera colado,
     * e aspa so precisa de escape dentro de atributo. Este retorno e
     * colado justamente dentro de um atributo, entao uma aspa dupla no
     * dado fechava o atributo e o que vinha depois virava atributo novo
     * do elemento -- `Maria" onmouseover="...` executava. O nome do
     * paciente e texto livre (`patients/forms.py::clean_full_name` so
     * apara espaco) e nao ha CSP que impeca o manipulador embutido.
     *
     * As duas linhas de `replace` sao o conserto inteiro: com `"` e `'`
     * escapados, o valor nao escapa de atributo de aspa simples nem de
     * aspa dupla, e o contexto de texto continua correto. */
    function escapar(texto) {
        var div = document.createElement('div');
        div.textContent = texto == null ? '' : String(texto);
        return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* Copiar leva código e descrição juntos: o código sozinho, colado num
     * laudo, obriga quem lê a procurar o que ele significa. */
    function botaoCopiar(codigo, descricao) {
        return '<button type="button" class="btn btn-sm btn-light-primary" ' +
               'data-nd-copy="' + escapar(codigo + ' — ' + descricao) + '">Copiar</button>';
    }

    function montar(config) {
        var campo = document.getElementById(config.input);
        var tabela = document.getElementById(config.table);
        var corpo = document.getElementById(config.rows);
        var status = document.getElementById(config.status);
        if (!campo || !tabela || !corpo || !status) return;

        var url = campo.getAttribute('data-url');
        var timer = null;
        /* Cada busca leva um número; só a resposta do número mais recente é
         * desenhada. Sem isso, uma resposta lenta de "epi" chegaria depois
         * da de "epilepsia" e sobrescreveria a lista certa pela errada. */
        var geracao = 0;

        function limpar(mensagem) {
            corpo.innerHTML = '';
            tabela.classList.add('d-none');
            status.textContent = mensagem || '';
            status.className = 'fs-12 text-muted mb-2';
        }

        function erro(mensagem) {
            corpo.innerHTML = '';
            tabela.classList.add('d-none');
            status.textContent = mensagem;
            /* Falha de serviço não é "nenhum resultado": lista vazia se lê
             * como "esse código não existe", que é o oposto do que houve. */
            status.className = 'fs-12 text-warning mb-2';
        }

        function buscar() {
            var termo = campo.value.trim();
            if (termo.length < config.minimo) {
                limpar(termo.length ? 'Digite pelo menos ' + config.minimo + ' caracteres.' : '');
                return;
            }
            var minha = ++geracao;
            status.textContent = 'Procurando…';
            status.className = 'fs-12 text-muted mb-2';

            fetch(url + '?q=' + encodeURIComponent(termo), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            })
                .then(function (r) {
                    if (!r.ok) throw new Error('http ' + r.status);
                    return r.json();
                })
                .then(function (dados) {
                    if (minha !== geracao) return;      /* resposta velha */
                    if (dados.ok === false) {
                        erro(dados.error || 'Não foi possível consultar agora.');
                        return;
                    }
                    var linhas = dados.results || [];
                    if (!linhas.length) {
                        limpar('Nenhum código encontrado para “' + termo + '”.');
                        return;
                    }
                    corpo.innerHTML = linhas.map(config.linha).join('');
                    tabela.classList.remove('d-none');
                    status.textContent = linhas.length + ' resultado(s).';
                    status.className = 'fs-12 text-muted mb-2';
                })
                .catch(function () {
                    if (minha !== geracao) return;
                    erro('Não foi possível consultar agora. Tente de novo em alguns instantes.');
                });
        }

        campo.addEventListener('input', function () {
            window.clearTimeout(timer);
            timer = window.setTimeout(buscar, config.espera);
        });
        campo.addEventListener('search', buscar);
        if (campo.value.trim()) buscar();
    }

    montar({
        input: 'nd-cid-q', table: 'nd-cid-table', rows: 'nd-cid-rows', status: 'nd-cid-status',
        minimo: 2,
        /* Local: 120ms basta para não consultar a cada tecla. */
        espera: 120,
        linha: function (item) {
            return '<tr><td class="ps-3"><code class="fw-bold">' + escapar(item.code) + '</code></td>' +
                   '<td class="fs-13">' + escapar(item.description) + '</td>' +
                   '<td class="pe-3 text-end">' + botaoCopiar(item.code, item.description) + '</td></tr>';
        }
    });

    montar({
        input: 'nd-tuss-q', table: 'nd-tuss-table', rows: 'nd-tuss-rows', status: 'nd-tuss-status',
        minimo: 2,
        /* Local, como o CID: a tabela e espelhada da ANS pelo worker, e a
         * busca nao sai do banco. */
        espera: 120,
        linha: function (item) {
            var vigencia = item.in_force
                ? '<span class="badge bg-soft-success text-success">vigente</span>'
                : '<span class="badge bg-soft-warning text-warning">encerrado</span>';
            return '<tr><td class="ps-3"><code class="fw-bold">' + escapar(item.code) + '</code></td>' +
                   '<td class="fs-13">' + escapar(item.description) + '</td>' +
                   '<td class="fs-12">' + vigencia + '</td>' +
                   '<td class="pe-3 text-end">' + botaoCopiar(item.code, item.description) + '</td></tr>';
        }
    });

    /* Delegado: as linhas nascem depois, e um listener por botão vazaria a
     * cada nova busca. */
    document.addEventListener('click', function (event) {
        var botao = event.target.closest('[data-nd-copy]');
        if (!botao) return;
        var texto = botao.getAttribute('data-nd-copy') || '';
        var original = botao.textContent;
        function avisar(ok) {
            botao.textContent = ok ? 'Copiado' : 'Selecione e copie';
            window.setTimeout(function () { botao.textContent = original; }, 1600);
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(texto).then(function () { avisar(true); },
                                                      function () { avisar(false); });
        } else {
            avisar(false);
        }
    });
}());
