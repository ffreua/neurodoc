/*
 * Modo produtivo do atendimento: teclado, rascunho local e consulta anterior.
 *
 * Três coisas que o médico faz o tempo todo e que custavam tirar a mão do
 * teclado ou sair da tela:
 *
 *   Ctrl+S      salva o que está aberto, sem caçar o botão
 *   Alt+1..9    troca de aba na ordem em que elas aparecem
 *   Alt+P       abre a consulta anterior por cima, e fecha
 *
 * E uma que ninguém faz até precisar: o rascunho local. A cada cinco
 * segundos o texto digitado vai para o `localStorage` deste navegador. Se
 * a aba cair, a bateria acabar ou o Wi-Fi da clínica sumir no meio de uma
 * história clínica de dez linhas, o texto está lá quando a página voltar.
 *
 * O rascunho **não** é o prontuário, e a tela diz isso: ele fica só neste
 * navegador, some ao salvar, e nada o envia ao servidor sozinho. O que
 * vale é o que foi salvo — quem decide gravar é sempre o médico.
 */
(function () {
    'use strict';

    var raiz = document.querySelector('[data-nd-atendimento]');
    if (!raiz) { return; }

    var encounterId = raiz.getAttribute('data-nd-atendimento');
    var editavel = raiz.getAttribute('data-nd-editavel') === '1';
    var INTERVALO_MS = 5000;
    var PREFIXO = 'neurodoc_draft_' + encounterId + '_';

    /* ------------------------------------------------------ rascunho local */

    function campos() {
        /* Só o que é texto longo de prontuário. Campo curto se redigita em
         * segundos, e guardar tudo encheria o `localStorage` do navegador
         * com o que não compensa restaurar. */
        return Array.prototype.slice.call(
            raiz.querySelectorAll('textarea[name][data-nd-encounter-draft]')
        ).filter(function (el) { return !el.disabled && !el.readOnly; });
    }

    function chave(campo) { return PREFIXO + campo.name; }

    /* O que o servidor mandou, lido uma vez no carregamento.
     *
     * É o valor do campo antes de qualquer digitação — não precisa de
     * atributo no HTML, e não tem como divergir do que está na tela. Serve
     * para duas perguntas: "isto que está digitado é diferente do que está
     * gravado?" (senão não é rascunho) e "o rascunho guardado ainda vale?"
     * (se o servidor já tem o mesmo texto, não vale). */
    var doServidor = {};
    campos().forEach(function (campo) { doServidor[campo.name] = campo.value || ''; });

    function valorGravado(campo) {
        return doServidor[campo.name] || '';
    }

    function guardar() {
        if (!editavel) { return; }
        campos().forEach(function (campo) {
            var atual = campo.value || '';
            var salvo = valorGravado(campo);
            try {
                if (atual === salvo) {
                    /* Igual ao que o servidor tem: não é rascunho, é o
                     * prontuário. Guardar criaria um aviso de restauração
                     * para um texto idêntico ao que já está na tela. */
                    window.localStorage.removeItem(chave(campo));
                } else {
                    window.localStorage.setItem(chave(campo), JSON.stringify({
                        texto: atual, em: Date.now()
                    }));
                }
            } catch (e) {
                /* Cota cheia ou armazenamento bloqueado (navegação privada,
                 * política do navegador). O atendimento continua: o rascunho
                 * é uma rede, não o chão. */
            }
        });
    }

    function lerRascunhos() {
        var achados = [];
        campos().forEach(function (campo) {
            var bruto = null;
            try { bruto = window.localStorage.getItem(chave(campo)); } catch (e) { return; }
            if (!bruto) { return; }
            var dados;
            try { dados = JSON.parse(bruto); } catch (e) { return; }
            if (!dados || typeof dados.texto !== 'string') { return; }
            if (dados.texto === valorGravado(campo) || !dados.texto.trim()) {
                /* Depois de um salvamento bem-sucedido, o valor guardado na
                 * saída da página é igual ao que o servidor devolveu. Ele já
                 * não é rascunho e não deve ficar esperando uma mudança futura
                 * para reaparecer como aviso antigo. */
                try { window.localStorage.removeItem(chave(campo)); } catch (e) { /* idem */ }
                return;
            }
            achados.push({ campo: campo, texto: dados.texto, em: dados.em || 0 });
        });
        return achados;
    }

    function limparRascunhosObsoletos() {
        /* Versões anteriores guardavam qualquer textarea da página, inclusive
         * `notes` da medicação e `physician_note` da hipótese. Remover só as
         * chaves deste atendimento que não correspondem mais a um campo
         * clínico evita que o defeito sobreviva ao deploy no navegador. */
        var validas = {};
        campos().forEach(function (campo) { validas[chave(campo)] = true; });
        var remover = [];
        try {
            for (var i = 0; i < window.localStorage.length; i += 1) {
                var item = window.localStorage.key(i);
                if (item && item.indexOf(PREFIXO) === 0 && !validas[item]) {
                    remover.push(item);
                }
            }
            remover.forEach(function (item) { window.localStorage.removeItem(item); });
        } catch (e) { /* armazenamento bloqueado; o atendimento continua */ }
    }

    function limpar() {
        campos().forEach(function (campo) {
            try { window.localStorage.removeItem(chave(campo)); } catch (e) { /* idem */ }
        });
    }

    function haMudanca() {
        return campos().some(function (campo) {
            return (campo.value || '') !== valorGravado(campo);
        });
    }

    function mostrarFalhaAoPreservar(mensagem) {
        var anterior = document.getElementById('nd-preservar-falhou');
        if (anterior) { anterior.remove(); }
        var aviso = document.createElement('div');
        aviso.id = 'nd-preservar-falhou';
        aviso.className = 'alert alert-danger';
        aviso.setAttribute('role', 'alert');
        aviso.textContent = mensagem;
        raiz.insertBefore(aviso, raiz.firstChild);
        aviso.scrollIntoView({ block: 'nearest' });
    }

    /* Medicação e hipótese têm formulários próprios e recarregam a página.
     * Se houver texto ainda não salvo, grava primeiro o formulário do
     * atendimento pelo endpoint que já protege versão e concorrência. O
     * clique no formulário auxiliar é uma ação explícita do médico; deixar
     * a nota para trás e obrigá-lo a restaurá-la na volta não é aceitável.
     *
     * O listener roda em captura para parar antes do spinner global, que
     * desabilita o botão contando que a navegação comece imediatamente. */
    raiz.addEventListener('submit', function (event) {
        var auxiliar = event.target;
        if (!auxiliar.matches || !auxiliar.matches('[data-nd-save-encounter-before-submit]')) {
            return;
        }
        if (auxiliar.dataset.ndEncounterSaved === '1') {
            delete auxiliar.dataset.ndEncounterSaved;
            return;
        }
        var principal = document.getElementById('nd-atendimento-livre');
        if (!principal || !haMudanca()) { return; }

        event.preventDefault();
        event.stopImmediatePropagation();
        guardar();
        var botao = event.submitter;

        window.fetch(principal.action, {
            method: 'POST',
            body: new FormData(principal),
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (dados) {
                if (!response.ok || !dados.ok) {
                    throw new Error(dados.error || 'Não foi possível salvar o atendimento.');
                }
                return dados;
            });
        }).then(function (dados) {
            var versao = principal.querySelector('[name="row_version"]');
            if (versao) { versao.value = dados.row_version; }
            campos().forEach(function (campo) {
                doServidor[campo.name] = campo.value || '';
            });
            limpar();
            auxiliar.dataset.ndEncounterSaved = '1';
            if (auxiliar.requestSubmit) {
                auxiliar.requestSubmit(botao || undefined);
            } else {
                auxiliar.submit();
            }
        }).catch(function (error) {
            mostrarFalhaAoPreservar(
                (error && error.message ? error.message : 'Não foi possível salvar o atendimento.')
                + ' A medicação ou hipótese não foi incluída; seu texto continua neste navegador.'
            );
        });
    }, true);

    /* Os rascunhos que a faixa está oferecendo agora. Vive aqui fora
     * porque os cliques são ligados **uma vez**, no arranque, e não
     * dentro de quem mostra a faixa.
     *
     * A primeira versão registrava os dois cliques dentro de
     * `avisarRascunho`, que só roda quando há rascunho. Parecia
     * equivalente — se a faixa não aparece, ninguém clica nela — até o dia
     * em que ela apareceu por outro motivo (o `hidden` derrotado pelo
     * `d-flex` do tema, ver `neurodoc.css`): aí havia uma faixa na tela
     * com dois botões que não faziam absolutamente nada, que é pior do
     * que não ter faixa. Botão visível sem comportamento é defeito por si
     * só, venha a visibilidade de onde vier. */
    var rascunhosOferecidos = [];

    function avisarRascunho(achados) {
        var aviso = document.getElementById('nd-rascunho');
        if (!aviso) { return; }
        rascunhosOferecidos = achados;
        var quando = achados.reduce(function (maior, r) { return Math.max(maior, r.em); }, 0);
        var texto = document.getElementById('nd-rascunho-texto');
        if (texto && quando) {
            texto.textContent = 'Há texto não salvo deste atendimento, guardado neste '
                + 'navegador em ' + new Date(quando).toLocaleString('pt-BR') + '.';
        }
        aviso.hidden = false;
    }

    function ligarBotoesDoRascunho() {
        var aviso = document.getElementById('nd-rascunho');
        if (!aviso) { return; }
        var restaurar = document.getElementById('nd-rascunho-restaurar');
        var descartar = document.getElementById('nd-rascunho-descartar');

        if (restaurar) {
            restaurar.addEventListener('click', function () {
                rascunhosOferecidos.forEach(function (r) {
                    r.campo.value = r.texto;
                    /* `input` para o autogrow do `app.js` recalcular a altura
                     * da caixa: restaurar dez linhas numa caixa de três
                     * esconderia sete. */
                    r.campo.dispatchEvent(new Event('input', { bubbles: true }));
                });
                aviso.hidden = true;
                var primeiro = rascunhosOferecidos[0] && rascunhosOferecidos[0].campo;
                if (primeiro) { primeiro.focus(); }
            });
        }
        if (descartar) {
            descartar.addEventListener('click', function () {
                limpar();
                aviso.hidden = true;
            });
        }
    }

    /* ------------------------------------------------------------ teclado */

    function formularioAtivo() {
        /* O formulário do que está em foco; se nada estiver, o da aba
         * aberta. Numa tela com sete abas e um formulário por aba, salvar
         * "o formulário" sem essa regra salvaria o primeiro da página. */
        var foco = document.activeElement;
        if (foco && foco.form && raiz.contains(foco.form)) { return foco.form; }
        var painel = raiz.querySelector('.tab-pane.active');
        if (painel) {
            var form = painel.querySelector('form');
            if (form) { return form; }
        }
        return raiz.querySelector('form');
    }

    function salvar() {
        var form = formularioAtivo();
        if (!form) { return false; }
        var botao = form.querySelector('button[type="submit"]:not([disabled])');
        if (!botao) { return false; }
        /* `requestSubmit` no botão, e não `form.submit()`: o primeiro dispara
         * o evento `submit`, que é onde `app.js` desabilita o botão e mostra
         * o spinner (`data-nd-busy`). `form.submit()` pula o evento, e com
         * ele a proteção contra o segundo clique. */
        if (form.requestSubmit) {
            form.requestSubmit(botao);
        } else {
            botao.click();
        }
        return true;
    }

    function abas() {
        return Array.prototype.slice.call(
            raiz.querySelectorAll('[data-bs-toggle="tab"]')
        ).filter(function (el) { return el.offsetParent !== null; });
    }

    /* -------------------------------------------------------- gaveta */

    var gaveta = document.getElementById('nd-gaveta');
    var fundo = document.getElementById('nd-gaveta-fundo');
    var focoAntesDaGaveta = null;

    function abrirGaveta() {
        if (!gaveta || gaveta.classList.contains('is-aberta')) { return; }
        focoAntesDaGaveta = document.activeElement;
        gaveta.classList.add('is-aberta');
        gaveta.setAttribute('aria-hidden', 'false');
        if (fundo) { fundo.hidden = false; }
        var fechar = document.getElementById('nd-gaveta-fechar');
        if (fechar) { fechar.focus(); }
    }

    function fecharGaveta() {
        if (!gaveta || !gaveta.classList.contains('is-aberta')) { return; }
        gaveta.classList.remove('is-aberta');
        gaveta.setAttribute('aria-hidden', 'true');
        if (fundo) { fundo.hidden = true; }
        if (focoAntesDaGaveta && document.contains(focoAntesDaGaveta)) {
            focoAntesDaGaveta.focus();
        }
        focoAntesDaGaveta = null;
    }

    document.addEventListener('click', function (event) {
        if (event.target.closest('[data-nd-gaveta-abrir]')) {
            event.preventDefault();
            abrirGaveta();
            return;
        }
        if (event.target.closest('#nd-gaveta-fechar') || event.target === fundo) {
            fecharGaveta();
        }
    });

    /* --------------------------------------------------------- atalhos */

    document.addEventListener('keydown', function (event) {
        var tecla = (event.key || '').toLowerCase();

        /* Ctrl+S / ⌘S. `preventDefault` sempre, inclusive quando não há o
         * que salvar: sem ele o navegador abre "Salvar página como", e um
         * prontuário aberto vira um arquivo `.html` na pasta de downloads
         * de quem só queria gravar a evolução. */
        if (tecla === 's' && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
            event.preventDefault();
            if (editavel) { salvar(); }
            return;
        }

        if (event.key === 'Escape' && gaveta && gaveta.classList.contains('is-aberta')) {
            event.preventDefault();
            fecharGaveta();
            return;
        }

        if (!event.altKey || event.ctrlKey || event.metaKey) { return; }

        if (tecla === 'p') {
            event.preventDefault();
            if (gaveta) {
                if (gaveta.classList.contains('is-aberta')) { fecharGaveta(); } else { abrirGaveta(); }
            }
            return;
        }

        /* Alt+1..9 seguem a ordem em que as abas aparecem na tela, e não uma
         * lista fixa de nomes: a tela estruturada tem sete abas e a de texto
         * livre não tem nenhuma. Numerar o que se vê é o que se consegue
         * decorar. */
        if (event.key >= '1' && event.key <= '9') {
            var todas = abas();
            var alvo = todas[Number(event.key) - 1];
            if (alvo) {
                event.preventDefault();
                alvo.click();
                /* O foco vai para a aba: quem trocou pelo teclado continua
                 * no teclado, e Tab daqui entra no conteúdo dela. */
                alvo.focus();
            }
        }
    });

    /* ------------------------------------------------------------- ligar */

    ligarBotoesDoRascunho();
    limparRascunhosObsoletos();
    var achados = lerRascunhos();
    if (achados.length) { avisarRascunho(achados); }

    if (editavel) {
        window.setInterval(guardar, INTERVALO_MS);
        /* Sair da página é o momento em que o rascunho mais importa, e é
         * o único que o intervalo pode perder. */
        window.addEventListener('pagehide', guardar);

        /* Salvou: o que está no servidor passa a ser a verdade, e o rascunho
         * deste atendimento deixa de existir. Roda no `submit`, e não na
         * volta da página, porque a volta é uma página nova — este código já
         * não está rodando quando ela chega. */
        raiz.addEventListener('submit', function (event) {
            if (event.target.id === 'nd-atendimento-livre'
                    || event.target.dataset.ndEncounterSaved === '1') {
                limpar();
            }
        });
    }
})();
