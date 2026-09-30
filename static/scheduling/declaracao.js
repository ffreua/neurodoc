/*
 * Abre o diálogo de impressão quando a declaração acabou de ser emitida.
 *
 * O gatilho é um atributo no `<body>`, posto pelo servidor só na resposta
 * do POST — e não na visualização. Assim a secretária pode ajustar os
 * horários quantas vezes precisar sem que a janela de impressão pule na
 * frente dela a cada conferida, e atualizar a página depois de imprimir não
 * reimprime.
 *
 * Arquivo externo em vez de `onclick`/`<script>` embutido de propósito: a
 * política de conteúdo que vem a seguir recusa script inline, e uma tela
 * que imprime é justamente a que ninguém testa de novo depois.
 */
(function () {
    'use strict';

    if (document.body.getAttribute('data-nd-imprimir') !== '1') return;

    // Um quadro de espera para o navegador terminar a pintura: chamar
    // `print()` antes disso já produziu folha em branco em Safari.
    window.setTimeout(function () { window.print(); }, 120);
})();
