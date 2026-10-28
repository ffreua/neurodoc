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

    /* Sair da página para emitir por modelo (`modelos/_na_conduta.html`).
     *
     * O mesmo cuidado do bloco acima, com duas diferenças. Vale nos **dois**
     * tipos de atendimento — no estruturado não existe o formulário único
     * `nd-atendimento-livre`, então o envio é montado aqui com os campos
     * que mudaram, e o salvamento grava só os que chegam. E o motivo é mais
     * forte: a emissão acrescenta o pedido à conduta no servidor; se o
     * rascunho antigo ficasse no navegador, a volta ofereceria restaurá-lo,
     * e restaurar apagaria o pedido da conduta.
     *
     * Atributo próprio, e não `data-nd-save-encounter-before-submit`: aquele
     * é contado pelo roteiro do texto livre, e este é outro caminho. */
    raiz.addEventListener('submit', function (event) {
        var saida = event.target;
        if (!saida.matches || !saida.matches('[data-nd-preservar-atendimento]')) {
            return;
        }
        if (saida.dataset.ndEncounterSaved === '1') {
            delete saida.dataset.ndEncounterSaved;
            return;
        }
        if (!editavel || !haMudanca()) { return; }

        event.preventDefault();
        event.stopImmediatePropagation();
        guardar();

        var dados = new FormData();
        var token = raiz.querySelector('[name="csrfmiddlewaretoken"]');
        var versao = raiz.querySelector('[name="row_version"]');
        if (token) { dados.append('csrfmiddlewaretoken', token.value); }
        if (versao) { dados.append('row_version', versao.value); }
        campos().forEach(function (campo) {
            if ((campo.value || '') !== valorGravado(campo)) {
                dados.append(campo.name, campo.value || '');
            }
        });

        window.fetch(saida.getAttribute('data-nd-preservar-atendimento'), {
            method: 'POST',
            body: dados,
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        }).then(function (response) {
            return response.json().catch(function () { return {}; }).then(function (resposta) {
                if (!response.ok || !resposta.ok) {
                    throw new Error(resposta.error || 'Não foi possível salvar o atendimento.');
                }
                return resposta;
            });
        }).then(function (resposta) {
            raiz.querySelectorAll('[name="row_version"]').forEach(function (campo) {
                campo.value = resposta.row_version;
            });
            campos().forEach(function (campo) {
                doServidor[campo.name] = campo.value || '';
            });
            limpar();
            saida.dataset.ndEncounterSaved = '1';
            if (saida.requestSubmit) {
                saida.requestSubmit();
            } else {
                saida.submit();
            }
        }).catch(function (error) {
            mostrarFalhaAoPreservar(
                (error && error.message ? error.message : 'Não foi possível salvar o atendimento.')
                + ' O modelo não foi aberto; seu texto continua neste navegador.'
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
        /* O seletor de modelos é navegação, não salvamento: Ctrl+S com o
         * foco nele salva o formulário da aba, e não abre a emissão. */
        if (foco && foco.form && raiz.contains(foco.form)
                && !foco.form.hasAttribute('data-nd-preservar-atendimento')) {
            return foco.form;
        }
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

    /* Duas gavetas: a consulta anterior e os dados de cadastro. Eram uma
     * só, endereçada por id fixo, e acrescentar a segunda do mesmo jeito
     * significaria duplicar abrir/fechar/foco/Esc -- e a segunda cópia
     * seria a que esqueceria de devolver o foco.
     *
     * O botão diz qual abrir em `data-nd-gaveta-abrir`; sem valor, abre a
     * da consulta anterior, que é como o botão existente já estava
     * escrito. O fundo escuro é um só, compartilhado: duas gavetas nunca
     * ficam abertas ao mesmo tempo. */
    var gaveta = document.getElementById('nd-gaveta');
    var fundo = document.getElementById('nd-gaveta-fundo');
    var focoAntesDaGaveta = null;
    var gavetaAberta = null;

    function abrirGaveta(alvo) {
        var elemento = alvo || gaveta;
        if (!elemento || elemento.classList.contains('is-aberta')) { return; }
        /* Abrir uma fecha a outra, sem devolver o foco no meio do
         * caminho: quem clicou quer a segunda, não voltar ao botão. */
        if (gavetaAberta && gavetaAberta !== elemento) {
            gavetaAberta.classList.remove('is-aberta');
            gavetaAberta.setAttribute('aria-hidden', 'true');
        } else {
            focoAntesDaGaveta = document.activeElement;
        }
        elemento.classList.add('is-aberta');
        elemento.setAttribute('aria-hidden', 'false');
        gavetaAberta = elemento;
        if (fundo) { fundo.hidden = false; }
        var fechar = elemento.querySelector('[data-nd-gaveta-fechar], #nd-gaveta-fechar');
        if (fechar) { fechar.focus(); }
    }

    function fecharGaveta() {
        if (!gavetaAberta) { return; }
        gavetaAberta.classList.remove('is-aberta');
        gavetaAberta.setAttribute('aria-hidden', 'true');
        gavetaAberta = null;
        if (fundo) { fundo.hidden = true; }
        if (focoAntesDaGaveta && document.contains(focoAntesDaGaveta)) {
            focoAntesDaGaveta.focus();
        }
        focoAntesDaGaveta = null;
    }

    function alternarGaveta(alvo) {
        var elemento = alvo || gaveta;
        if (!elemento) { return; }
        if (elemento.classList.contains('is-aberta')) { fecharGaveta(); }
        else { abrirGaveta(elemento); }
    }

    document.addEventListener('click', function (event) {
        var botao = event.target.closest('[data-nd-gaveta-abrir]');
        if (botao) {
            event.preventDefault();
            var id = botao.getAttribute('data-nd-gaveta-abrir');
            alternarGaveta(id ? document.getElementById(id) : gaveta);
            return;
        }
        if (event.target.closest('[data-nd-gaveta-fechar], #nd-gaveta-fechar')
            || event.target === fundo) {
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

        if (event.key === 'Escape' && gavetaAberta) {
            event.preventDefault();
            fecharGaveta();
            return;
        }

        if (!event.altKey || event.ctrlKey || event.metaKey) { return; }

        if (tecla === 'p') {
            event.preventDefault();
            alternarGaveta(gaveta);
            return;
        }

        /* Alt+D: dados de cadastro. A letra é a inicial, como o P da
         * consulta anterior -- e o atalho está escrito no botão, porque
         * atalho que ninguém descobre não existe. */
        if (tecla === 'd') {
            event.preventDefault();
            alternarGaveta(document.getElementById('nd-gaveta-ficha'));
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
