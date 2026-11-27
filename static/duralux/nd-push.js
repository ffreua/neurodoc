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

    /* O estado que o push usa de fato. No app instalado do Android a permissão
     * do site e a do app são duas coisas (o Android pode dizer "Permitido" com o
     * site em "Perguntar"), e `Notification.permission` sozinho não conta a
     * história inteira — por isso as três respostas vão ao diagnóstico. */
    function estadoDoPush() {
        var push = registro && registro.pushManager.permissionState
            ? registro.pushManager.permissionState({userVisibleOnly: true}).catch(function () { return '?'; })
            : Promise.resolve('?');
        var site = navigator.permissions && navigator.permissions.query
            ? navigator.permissions.query({name: 'notifications'})
                .then(function (r) { return r.state; }, function () { return '?'; })
            : Promise.resolve('?');
        return Promise.all([push, site]).then(function (r) {
            return {push: r[0], site: r[1], notificacao: Notification.permission};
        });
    }

    /* Uma linha para o print: com ela, "não funcionou" vira "o site está em
     * prompt no Chrome 131 instalado", e a próxima correção não é palpite. */
    function diagnostico(extra) {
        var linha = raiz.querySelector('[data-nd-push-diag]');
        if (!linha) { return; }
        var ua = navigator.userAgent;
        var navegador = (ua.match(/SamsungBrowser\/[\d.]+|EdgA?\/[\d.]+|Firefox\/[\d.]+|CriOS\/[\d.]+|Chrome\/[\d.]+|Version\/[\d.]+ .*Safari/) || ['?'])[0];
        estadoDoPush().then(function (e) {
            linha.textContent = 'Diagnóstico: ' + navegador.split(' ')[0] + ' · ' +
                (instalado ? 'app instalado' : 'navegador') + ' · push=' + e.push +
                ' · site=' + e.site + ' · notificação=' + e.notificacao +
                (extra ? ' · ' + extra : '');
            linha.hidden = false;
        });
    }

    function conferir() {
        estadoDoPush().then(function (e) {
            if (e.push === 'denied' || e.notificacao === 'denied') {
                mostrar('bloqueado');
                diagnostico();
                return;
            }
            atual().then(function (inscricao) {
                mostrar(inscricao ? 'ligado' : 'desligado');
            });
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
            /* O pedido de permissão sai **dentro do toque** (o navegador recusa
             * fora dele), e não é abandonado por prazo: no app instalado do
             * Android o Chrome pode não mostrá-lo (2026-11-27: o Android dizia
             * "Permitido" e a promessa ficava pendente). Passados 8 s, aparece o
             * caminho da permissão **do site** no Chrome, e o pedido continua
             * valendo — liberado lá, a ativação segue sozinha. */
            // As duas formas do pedido: a promessa e a função de retorno antiga.
            // Navegador derivado do Chromium pode atender só uma delas, e esperar
            // pela que ele não atende era um pedido "sem resposta" para sempre.
            var pedido = new Promise(function (resolve) {
                var promessa = Notification.requestPermission(resolve);
                if (promessa && promessa.then) { promessa.then(resolve); }
            });
            var dica = window.setTimeout(function () {
                // A permissão é do site **no navegador que instalou o app**: o
                // app do Samsung Internet não lê o que foi liberado no Chrome.
                var site = window.location.hostname;
                aviso(/SamsungBrowser/.test(navigator.userAgent)
                    ? 'O pedido de permissão não apareceu. Este app foi instalado pelo Samsung ' +
                      'Internet: abra o app Internet da Samsung (fora deste app), entre em ' + site +
                      ', vá a Notificações e toque em Ativar neste aparelho — lá o pedido aparece. ' +
                      'Se não aparecer: Internet → menu ☰ → Configurações → Sites e downloads → ' +
                      'Notificações → deixe ligado "Permitir solicitações de notificação" e libere ' +
                      site + '. Depois volte a este app.'
                    : 'O pedido de permissão não apareceu. No Chrome: menu ⋮ → Configurações → ' +
                      'Configurações do site → Notificações → ' + site + ' → Permitir (e, se ' +
                      'houver, desligue "Usar mensagens mais discretas"). Ou abra ' + site +
                      ' no Chrome, fora do app, e ative por lá.');
                diagnostico('pedido sem resposta');
                botao.textContent = rotulo;
                botao.disabled = false;
            }, 8000);
            botao.textContent = 'Pedindo a permissão…';
            var permissao = estadoDoPush().then(function (e) {
                return e.push === 'granted' ? 'granted' : pedido;
            });
            feito = permissao.then(function (resposta) {
                window.clearTimeout(dica);
                aviso('');
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
                window.clearTimeout(dica);
                botao.textContent = rotulo;
                diagnostico(erro && erro.name && erro.name !== 'Error' ? erro.name : '');
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
