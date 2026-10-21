/*
 * Novo documento médico: mostra só os campos do tipo escolhido.
 *
 * O formulário declara um grupo por tipo (`data-nd-doc-kind`) e todos vêm
 * visíveis do servidor. Isto os reduz ao grupo do tipo selecionado — e a
 * ordem importa: sem JavaScript a tela fica como estava, com tudo à mostra,
 * em vez de ficar com todos os campos escondidos e sem como preenchê-los.
 */
(function () {
    'use strict';

    var form = document.getElementById('medical-document-form');
    if (!form) return;

    var kindField = form.querySelector('[name="kind"]');
    var groups = form.querySelectorAll('[data-nd-doc-kind]');
    if (!kindField || !groups.length) return;

    function apply() {
        var chosen = kindField.value;
        groups.forEach(function (group) {
            var mine = group.getAttribute('data-nd-doc-kind') === chosen;
            group.hidden = !mine;
            /* Campo escondido sai da validação do navegador e da navegação
             * por Tab. `hidden` some da tela, mas um campo dentro de um
             * elemento oculto continua alcançável pelo teclado — e quem
             * navega assim cairia num campo que não existe para o tipo
             * escolhido. */
            group.querySelectorAll('input, select, textarea').forEach(function (input) {
                input.disabled = !mine;
            });
        });
    }

    kindField.addEventListener('change', apply);
    apply();

    /* Dentro da receita: o bloco do formato escolhido. A receita eletrônica
     * do SNCR (`sncr_*`) usa os itens estruturados; as impressas, o texto
     * livre. O formato só existe com a receita escolhida, e o bloco escondido
     * sai do envio (`disabled`) — senão os itens vazios iriam junto da
     * receita impressa e vice-versa. */
    var formatField = form.querySelector('[name="prescription_format"]');
    var rxGroups = form.querySelectorAll('[data-nd-rx]');
    if (!formatField || !rxGroups.length) return;

    function applyFormat() {
        var isPrescription = kindField.value === 'prescription';
        var wanted = (formatField.value || '').indexOf('sncr_') === 0 ? 'sncr' : 'impressa';
        rxGroups.forEach(function (group) {
            var mine = isPrescription && group.getAttribute('data-nd-rx') === wanted;
            group.hidden = !mine;
            group.querySelectorAll('input, select, textarea').forEach(function (input) {
                input.disabled = !mine;
            });
        });
    }

    formatField.addEventListener('change', applyFormat);
    kindField.addEventListener('change', applyFormat);
    applyFormat();
})();
