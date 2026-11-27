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

    /*
     * "Sair" desliga os avisos no celular deste aparelho (Etapa 2,
     * notifications/apps.py): cancela a inscrição no navegador e manda o
     * endereço dela junto com o formulário, para o servidor tirar a linha.
     * Com prazo: se o navegador demorar, sai assim mesmo — sair não pode
     * ficar preso esperando o serviço de push.
     */
    document.addEventListener('submit', function (evento) {
        var form = evento.target;
        if (!form || form.getAttribute('data-nd-push-saindo') ||
            !/\/accounts\/logout\/$/.test(new URL(form.action, window.location.href).pathname)) {
            return;
        }
        evento.preventDefault();
        form.setAttribute('data-nd-push-saindo', '1');
        var enviado = false;
        function sair() {
            if (enviado) { return; }
            enviado = true;
            form.submit();
        }
        window.setTimeout(sair, 1500);
        navigator.serviceWorker.getRegistration('/').then(function (registro) {
            return registro && registro.pushManager ? registro.pushManager.getSubscription() : null;
        }).then(function (inscricao) {
            if (!inscricao) { return null; }
            var campo = document.createElement('input');
            campo.type = 'hidden';
            campo.name = 'nd_push_endpoint';
            campo.value = inscricao.endpoint;
            form.appendChild(campo);
            return inscricao.unsubscribe();
        }).catch(function () { return null; }).then(sair);
    }, true);
})();
