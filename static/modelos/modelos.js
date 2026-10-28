/* Busca na TUSS para os modelos e a emissão por modelo.
 *
 * Insere "CÓDIGO DESCRIÇÃO" como uma linha nova na última caixa de lista
 * (`textarea[data-nd-tuss-alvo]`) em que o cursor esteve — a lista de
 * exames de uma categoria, ou os procedimentos da cirurgia. A linha entra
 * no formato que `modelos/estrutura.py` lê, e o médico pode editá-la ali.
 *
 * Nunca `innerHTML`: descrição de catálogo vai por `textContent`. Falha de
 * rede ou TUSS ainda não sincronizada só avisam; a caixa continua aceitando
 * digitação livre.
 */
(function () {
    'use strict';

    function ligar(caixa) {
        var url = caixa.getAttribute('data-nd-tuss-busca');
        var campo = caixa.querySelector('input');
        var lista = caixa.querySelector('[data-nd-tuss-resultados]');
        var escopo = caixa.closest('form') || document;
        var alvo = escopo.querySelector('textarea[data-nd-tuss-alvo]');
        var espera = null;
        var controle = null;
        if (!url || !campo || !lista) { return; }

        escopo.addEventListener('focusin', function (event) {
            var el = event.target;
            if (el && el.matches && el.matches('textarea[data-nd-tuss-alvo]')) { alvo = el; }
        });

        function limpar() {
            while (lista.firstChild) { lista.removeChild(lista.firstChild); }
        }

        function aviso(texto) {
            limpar();
            var p = document.createElement('div');
            p.className = 'list-group-item fs-12 text-muted';
            p.textContent = texto;
            lista.appendChild(p);
        }

        function inserir(linha) {
            if (!alvo) { return; }
            var atual = alvo.value.replace(/\s+$/, '');
            alvo.value = atual ? atual + '\n' + linha : linha;
            alvo.focus();
            campo.value = '';
            limpar();
        }

        function mostrar(dados) {
            limpar();
            if (!dados || dados.ok === false) {
                aviso((dados && dados.error) || 'A busca na TUSS não respondeu. Digite o código à mão.');
                return;
            }
            var resultados = dados.results || [];
            if (!resultados.length) { aviso('Nenhum código encontrado.'); return; }
            resultados.forEach(function (r) {
                var botao = document.createElement('button');
                botao.type = 'button';
                botao.className = 'list-group-item list-group-item-action fs-12';
                botao.textContent = r.code + ' — ' + r.description + (r.in_force === false ? ' (encerrado)' : '');
                botao.addEventListener('click', function () { inserir(r.code + ' ' + r.description); });
                lista.appendChild(botao);
            });
        }

        function buscar() {
            var termo = campo.value.trim();
            if (termo.length < 2) { limpar(); return; }
            if (controle && controle.abort) { controle.abort(); }
            controle = window.AbortController ? new window.AbortController() : null;
            window.fetch(url + '?q=' + encodeURIComponent(termo), {
                credentials: 'same-origin',
                headers: { 'Accept': 'application/json' },
                signal: controle ? controle.signal : undefined
            }).then(function (r) {
                return r.json();
            }).then(mostrar).catch(function (erro) {
                if (erro && erro.name === 'AbortError') { return; }
                aviso('A busca na TUSS não respondeu. Digite o código à mão.');
            });
        }

        campo.addEventListener('input', function () {
            window.clearTimeout(espera);
            espera = window.setTimeout(buscar, 220);
        });
        campo.addEventListener('keydown', function (event) {
            /* Enter na busca não envia o formulário do modelo. */
            if (event.key === 'Enter') { event.preventDefault(); buscar(); }
        });
    }

    document.querySelectorAll('[data-nd-tuss-busca]').forEach(ligar);
})();
