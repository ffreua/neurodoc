/* Autocomplete de naturalidade, pelo catálogo de municípios do IBGE.
 *
 * **Lista própria, e não `<datalist>`.** A primeira versão usava o
 * elemento nativo, pela razão certa: teclado, leitor de tela e toque de
 * graça. No primeiro teste em celular ele simplesmente não apareceu —
 * `<datalist>` é suportado no Android no papel, e na prática o menu não
 * abre em boa parte dos navegadores móveis, ou exige tocar numa seta de
 * dois pixels que o teclado cobre. Num cadastro que a secretária
 * preenche no balcão, autocomplete que não abre é autocomplete que não
 * existe.
 *
 * A lista aqui é a mesma do autocomplete de medicamento
 * (`catalogs/medicamentos.js`), que já passou por celular: botões de
 * verdade, com alvo de toque, que `check_mobile` mede.
 *
 * Sem este arquivo carregado, o campo continua funcionando como texto
 * livre. O autocomplete é conveniência, nunca requisito — e quem nasceu
 * fora do Brasil não está em catálogo de município nenhum.
 */
(function () {
    'use strict';

    /* Duzentos e cinquenta milissegundos: tempo de terminar de digitar
     * "são jo" sem disparar seis consultas no caminho. */
    var ESPERA_MS = 250;

    function criarLista(campo) {
        var lista = document.createElement('div');
        lista.className = 'nd-natur-lista';
        lista.hidden = true;
        lista.setAttribute('role', 'listbox');
        campo.parentNode.classList.add('nd-natur-ancora');
        campo.parentNode.appendChild(lista);
        return lista;
    }

    function ligar(campo) {
        var url = campo.dataset.ndMunicipioUrl;
        if (!url) { return; }
        var lista = criarLista(campo);
        var relogio = null;

        function fechar() {
            lista.hidden = true;
            lista.textContent = '';
        }

        /* O campo de UF da mesma ficha. Filtrar por UF é o que faz
         * "são josé" em Santa Catarina devolver três opções em vez de
         * dezenove — e é por isso que a UF vem **antes** da cidade no
         * formulário. */
        function ufEscolhida() {
            var campoUf = document.querySelector('[data-nd-municipio-uf]');
            return campoUf && campoUf.value ? campoUf.value : '';
        }

        function escolher(item) {
            campo.value = item.nome;
            var campoUf = document.querySelector('[data-nd-municipio-uf]');
            /* Preenche a UF junto, quando ela ainda não foi escolhida:
             * quem seleciona "Campinas/SP" já disse a UF, e pedir de novo
             * é pedir duas vezes a mesma coisa. Se a pessoa já escolheu
             * uma UF, a dela manda — a lista foi filtrada por ela. */
            if (campoUf && !campoUf.value && item.uf) {
                campoUf.value = item.uf;
                campoUf.dispatchEvent(new Event('change', { bubbles: true }));
            }
            fechar();
        }

        function desenhar(resultados) {
            lista.textContent = '';
            if (!resultados.length) {
                var vazio = document.createElement('p');
                vazio.className = 'nd-natur-vazio';
                vazio.textContent = 'Nenhum município com esse nome. '
                    + 'Pode digitar assim mesmo — quem nasceu fora do Brasil '
                    + 'não está nesta lista.';
                lista.appendChild(vazio);
                lista.hidden = false;
                return;
            }
            resultados.forEach(function (item) {
                var opcao = document.createElement('button');
                opcao.type = 'button';
                opcao.className = 'nd-natur-opcao';
                opcao.setAttribute('role', 'option');
                opcao.textContent = item.label;
                opcao.addEventListener('click', function () { escolher(item); });
                lista.appendChild(opcao);
            });
            lista.hidden = false;
        }

        function buscar() {
            var termo = campo.value.trim();
            if (termo.length < 2) { fechar(); return; }
            var alvo = url + '?q=' + encodeURIComponent(termo);
            var uf = ufEscolhida();
            if (uf) { alvo += '&uf=' + encodeURIComponent(uf); }
            fetch(alvo, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.ok ? r.json() : { results: [] }; })
                .then(function (dados) { desenhar(dados.results || []); })
                /* Falha de rede não pode atrapalhar o cadastro: o campo é
                 * texto livre, e sem sugestão ele continua servindo. */
                .catch(function () { fechar(); });
        }

        campo.addEventListener('input', function () {
            window.clearTimeout(relogio);
            relogio = window.setTimeout(buscar, ESPERA_MS);
        });

        campo.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') { fechar(); }
        });

        /* Fechar ao tocar fora. `mousedown`/`touchstart` e não `blur`: o
         * `blur` dispara **antes** do clique na opção e fechava a lista
         * sem deixar escolher nada — que é o jeito mais fácil de um
         * autocomplete parecer quebrado. */
        document.addEventListener('mousedown', function (event) {
            if (event.target !== campo && !lista.contains(event.target)) { fechar(); }
        });
        document.addEventListener('touchstart', function (event) {
            if (event.target !== campo && !lista.contains(event.target)) { fechar(); }
        }, { passive: true });
    }

    function iniciar() {
        document.querySelectorAll('[data-nd-municipio]').forEach(ligar);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciar);
    } else {
        iniciar();
    }
}());
