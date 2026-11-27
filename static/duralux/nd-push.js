/*
 * Os avisos no celular (Etapa 2 do aplicativo instalado, notifications/push.py).
 *
 * Só na Central de notificações, dentro de `[data-nd-push]`. O navegador só
 * pede a permissão depois de um toque no botão — pedir ao abrir a tela é o
 * que faz a pessoa clicar em "Bloquear" sem ler, e o bloqueio não se desfaz
 * por aqui, só nas configurações do aparelho.
 *
 * Cada estado mostra um bloco (`data-nd-push-estado="..."`) e esconde os
 * outros; o texto de cada um está no template, não aqui.
 */
(function () {
    'use strict';
    var raiz = document.querySelector('[data-nd-push]');
    if (!raiz) { return; }

    function mostrar(estado) {
        raiz.querySelectorAll('[data-nd-push-estado]').forEach(function (bloco) {
            bloco.hidden = bloco.getAttribute('data-nd-push-estado') !== estado;
        });
    }

    function aviso(texto) {
        var linha = raiz.querySelector('[data-nd-push-msg]');
        if (linha) { linha.textContent = texto || ''; }
    }

    function token() {
        var campo = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (campo) { return campo.value; }
        return (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/) || [])[1] || '';
    }

    function enviar(endereco, corpo) {
        return fetch(endereco, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': token()},
            body: JSON.stringify(corpo || {})
        }).then(function (resposta) {
            return resposta.json().catch(function () { return {}; }).then(function (dados) {
                if (!resposta.ok) { throw new Error(dados.erro || 'Não foi possível concluir.'); }
                return dados;
            });
        });
    }

    function chave(base64) {
        var preenchida = (base64 + '===='.slice((base64.length % 4) || 4))
            .replace(/-/g, '+').replace(/_/g, '/');
        var bruto = window.atob(preenchida);
        var bytes = new Uint8Array(bruto.length);
        for (var i = 0; i < bruto.length; i++) { bytes[i] = bruto.charCodeAt(i); }
        return bytes;
    }

    var instalado = window.matchMedia('(display-mode: standalone)').matches ||
        window.navigator.standalone === true;
    var ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

    if (!('serviceWorker' in navigator) || !window.isSecureContext) {
        mostrar('sem-suporte');
        return;
    }
    if (!('PushManager' in window) || !('Notification' in window)) {
        // No iPhone o push só existe no app instalado (iOS 16.4 ou mais novo).
        mostrar(ios && !instalado ? 'iphone' : 'sem-suporte');
        return;
    }

    var registro = null;
    function atual() {
        return registro.pushManager.getSubscription();
    }

    function conferir() {
        if (Notification.permission === 'denied') { mostrar('bloqueado'); return; }
        atual().then(function (inscricao) {
            mostrar(inscricao ? 'ligado' : 'desligado');
        });
    }

    navigator.serviceWorker.ready.then(function (pronto) {
        registro = pronto;
        conferir();
    });

    raiz.addEventListener('click', function (evento) {
        var botao = evento.target.closest('[data-nd-push-acao]');
        if (!botao || !registro) { return; }
        evento.preventDefault();
        var acao = botao.getAttribute('data-nd-push-acao');
        botao.disabled = true;
        aviso('');
        var feito;
        if (acao === 'ligar') {
            feito = Notification.requestPermission().then(function (permissao) {
                if (permissao !== 'granted') { throw new Error('bloqueado'); }
                return registro.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: chave(raiz.getAttribute('data-nd-push-chave'))
                });
            }).then(function (inscricao) {
                return enviar(raiz.getAttribute('data-nd-push-ativar'), inscricao.toJSON());
            }).then(function () {
                window.location.reload();
            });
        } else if (acao === 'testar') {
            feito = atual().then(function (inscricao) {
                if (!inscricao) { throw new Error('Este aparelho não está com os avisos ligados.'); }
                return enviar(raiz.getAttribute('data-nd-push-testar'), {endpoint: inscricao.endpoint});
            }).then(function () {
                aviso('Aviso de teste enviado. Ele chega em alguns segundos.');
            });
        } else if (acao === 'desligar') {
            feito = atual().then(function (inscricao) {
                if (!inscricao) { return null; }
                var endpoint = inscricao.endpoint;
                return inscricao.unsubscribe().then(function () {
                    return enviar(raiz.getAttribute('data-nd-push-desativar'), {endpoint: endpoint});
                });
            }).then(function () {
                window.location.reload();
            });
        }
        if (!feito) { botao.disabled = false; return; }
        feito.catch(function (erro) {
            if (erro && erro.message === 'bloqueado') { conferir(); }
            else { aviso((erro && erro.message) || 'Não foi possível concluir.'); }
        }).then(function () { botao.disabled = false; });
    });
})();
