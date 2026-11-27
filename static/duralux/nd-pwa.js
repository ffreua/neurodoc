/*
 * Registra o service worker do aplicativo instalado (`base/pwa.py`).
 *
 * Só nas telas da equipe (o template decide), e só onde há worker: navegador
 * antigo e página fora de HTTPS seguem como sempre, sem nada a perder — o
 * worker só acrescenta a tela sem internet.
 *
 * A falha ao registrar vai para o console e não para a tela: o sistema
 * funciona igual sem o worker, e um aviso na tela por isso seria ruído.
 */
(function () {
    'use strict';
    if (!('serviceWorker' in navigator) || !window.isSecureContext) { return; }
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch(function (erro) {
            if (window.console) { console.warn('Service worker não registrado:', erro); }
        });
    });
})();
