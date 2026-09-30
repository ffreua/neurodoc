/*
 * Sobreposto de evolução: carrega o gráfico sob demanda.
 *
 * O conteúdo vem pronto do servidor (`clinical:evolucao`), como fragmento
 * de HTML. O desenho inteiro — inclusive a aritmética do eixo do tempo —
 * mora em `clinical/series.py`, onde o roteiro de verificação o confere.
 * Aqui só se busca e se troca o miolo do modal.
 *
 * Carregar sob demanda é o motivo de o recurso existir assim: a linha do
 * tempo é a tela que se abre para ver a lista de consultas, e ela não pode
 * pagar uma varredura de achados e laudos para quem não pediu gráfico
 * nenhum.
 */
(function () {
    'use strict';

    var modal = document.getElementById('evolucao-modal');
    if (!modal) return;

    var corpo = modal.querySelector('[data-nd-evolucao-corpo]');
    var base = modal.getAttribute('data-evolucao-url');
    if (!corpo || !base) return;

    var carregado = false;

    function esperando() {
        corpo.innerHTML =
            '<div class="text-center py-5 text-muted fs-13">Montando o gráfico…</div>';
    }

    function carregar(serie) {
        esperando();
        var url = serie ? base + '?serie=' + encodeURIComponent(serie) : base;
        fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
            .then(function (resposta) {
                if (!resposta.ok) throw new Error(resposta.status);
                return resposta.text();
            })
            .then(function (html) {
                corpo.innerHTML = html;
                carregado = true;
            })
            .catch(function () {
                // Sem detalhe técnico na tela: quem está com o paciente na
                // frente precisa saber que não carregou e que pode tentar de
                // novo, não do código HTTP.
                corpo.innerHTML =
                    '<div class="alert alert-warning fs-13 mb-0" role="alert">' +
                    'Não foi possível montar o gráfico agora. Feche e abra novamente.' +
                    '</div>';
            });
    }

    modal.addEventListener('show.bs.modal', function () {
        if (!carregado) carregar('');
    });

    // O seletor de série nasce dentro do fragmento, a cada troca. Ouvir no
    // modal em vez de no `<select>` é o que faz o segundo `change` funcionar
    // — o elemento do primeiro já não existe.
    corpo.addEventListener('change', function (evento) {
        var alvo = evento.target;
        if (alvo && alvo.hasAttribute('data-nd-serie')) carregar(alvo.value);
    });
})();
