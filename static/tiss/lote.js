/* Lote TISS: enquanto o arquivo é gerado no worker, a página se recarrega
 * sozinha — poucas vezes, porque a geração leva segundos. Sem o atributo
 * `data-tiss-gerando` na página, não faz nada. */
(function () {
    'use strict';
    var marca = document.querySelector('[data-tiss-gerando]');
    if (!marca) { return; }
    var chave = 'tiss-lote-recargas-' + marca.getAttribute('data-tiss-gerando');
    var feitas = 0;
    try { feitas = parseInt(window.sessionStorage.getItem(chave) || '0', 10); } catch (e) { feitas = 0; }
    if (feitas >= 20) { return; }
    window.setTimeout(function () {
        try { window.sessionStorage.setItem(chave, String(feitas + 1)); } catch (e) { /* sem armazenamento */ }
        window.location.reload();
    }, 3000);
}());
