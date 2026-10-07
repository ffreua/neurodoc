/* Autocomplete de naturalidade, pelo catálogo de municípios do IBGE.
 *
 * Usa `<datalist>` nativo, e não uma lista desenhada à mão como a do
 * medicamento. A diferença de escolha tem motivo: o medicamento precisa
 * de rótulo com tarja, de botão "usar assim mesmo" e de preencher três
 * campos ao escolher — nada disso cabe num `<datalist>`. Aqui o que se
 * quer é sugerir um nome de cidade. O nativo dá teclado, leitor de tela
 * e toque no celular de graça, e **não impede** quem digita um nome que
 * não está na lista — que é exatamente o caso de quem nasceu fora do
 * Brasil.
 *
 * Sem este arquivo carregado, o campo continua funcionando como texto
 * livre. O autocomplete é conveniência, nunca requisito.
 */
(function () {
    'use strict';

    /* Duzentos e cinquenta milissegundos: tempo de a pessoa terminar de
     * digitar "são jo" sem disparar seis consultas no caminho. */
    var ESPERA_MS = 250;

    function ligar(campo) {
        var url = campo.dataset.ndMunicipioUrl;
        var lista = document.getElementById(campo.getAttribute('list') || '');
        if (!url || !lista) { return; }

        var relogio = null;
        var ultimoTermo = '';

        /* O campo de UF da mesma ficha, quando existe. Filtrar por UF é o
         * que faz "são josé" em Santa Catarina devolver três opções em vez
         * de dezenove. */
        function ufEscolhida() {
            var campoUf = document.querySelector('[data-nd-municipio-uf]');
            return campoUf && campoUf.value ? campoUf.value : '';
        }

        function preencher(resultados) {
            lista.textContent = '';
            resultados.forEach(function (item) {
                var opcao = document.createElement('option');
                /* O `value` é só o nome da cidade, e o rótulo mostra a UF.
                 * Pôr "São Paulo/SP" no `value` gravaria a UF dentro do
                 * campo da cidade, e a ficha passaria a ter a sigla duas
                 * vezes — uma no lugar certo e outra colada no nome. */
                opcao.value = item.nome;
                opcao.label = item.label;
                lista.appendChild(opcao);
            });
        }

        function buscar() {
            var termo = campo.value.trim();
            if (termo.length < 2 || termo === ultimoTermo) { return; }
            ultimoTermo = termo;
            var alvo = url + '?q=' + encodeURIComponent(termo);
            var uf = ufEscolhida();
            if (uf) { alvo += '&uf=' + encodeURIComponent(uf); }
            fetch(alvo, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.ok ? r.json() : { results: [] }; })
                .then(function (dados) { preencher(dados.results || []); })
                /* Falha de rede não pode quebrar o cadastro: o campo é
                 * texto livre, e sem sugestão ele continua servindo. */
                .catch(function () { });
        }

        campo.addEventListener('input', function () {
            window.clearTimeout(relogio);
            relogio = window.setTimeout(buscar, ESPERA_MS);
        });
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
