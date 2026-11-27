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

    /* A promessa, ou o erro com a mensagem se ela não resolver no prazo. */
    function prazo(promessa, ms, mensagem) {
        return new Promise(function (resolve, reject) {
            var relogio = window.setTimeout(function () { reject(new Error(mensagem)); }, ms);
            promessa.then(function (valor) { window.clearTimeout(relogio); resolve(valor); },
                function (erro) { window.clearTimeout(relogio); reject(erro); });
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
            var rotulo = botao.textContent;
            /* Cada passo com prazo e com o que fazer. Sem prazo, o botão ficava
             * desbotado para sempre no app instalado do Android (2026-11-27): o
             * Chrome pode pedir a permissão pelo sininho "discreto" da barra de
             * endereço, e o app instalado não tem barra — a promessa nunca
             * resolve, e nada dizia por quê. Permissão já dada não é pedida de novo. */
            var permissao = Notification.permission === 'granted'
                ? Promise.resolve('granted')
                : (botao.textContent = 'Pedindo a permissão…', prazo(Notification.requestPermission(), 8000,
                    'O pedido de permissão não apareceu. Libere as notificações deste site ' +
                    '(no app instalado: segure o ícone → Informações do app → Notificações → ' +
                    'Permitir; no Chrome: toque no cadeado ao lado do endereço → Permissões → ' +
                    'Notificações) e toque de novo em Ativar.'));
            feito = permissao.then(function (resposta) {
                if (resposta !== 'granted') { throw new Error('bloqueado'); }
                botao.textContent = 'Registrando o aparelho…';
                return prazo(registro.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: chave(raiz.getAttribute('data-nd-push-chave'))
                }), 20000, 'O serviço de avisos do celular não respondeu. Confira a internet ' +
                    'e tente de novo; se continuar, abra o sistema pelo Chrome e ative por lá.');
            }).then(function (inscricao) {
                botao.textContent = 'Gravando…';
                return prazo(enviar(raiz.getAttribute('data-nd-push-ativar'), inscricao.toJSON()),
                    15000, 'O sistema não respondeu a tempo. Tente de novo.');
            }).then(function () {
                window.location.reload();
            });
            feito = feito.catch(function (erro) {
                botao.textContent = rotulo;
                throw erro;
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
