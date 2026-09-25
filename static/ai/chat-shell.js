/* Comportamento do layout de chat: filtro, rolagem, composer e busca de
 * paciente.
 *
 * Separado de `chat.js`, que cuida do streaming (SSE) e já estava
 * homologado. Misturar as duas coisas num arquivo faria uma mudança de
 * layout arriscar o streaming, que é a parte que não pode quebrar.
 */
(function () {
    'use strict';

    /* ---------------------------------------------- rolagem da conversa */

    /* Abrir uma conversa mostra o fim dela, não o começo: a última
     * mensagem é a que interessa, e rolar até o fim é a primeira coisa
     * que a pessoa faria à mão. */
    var painel = document.getElementById('messages');
    if (painel) {
        painel.scrollTop = painel.scrollHeight;

        /* Durante o streaming o texto cresce, e a rolagem tem de
         * acompanhar — mas só se quem lê está no fim. Rolar para trás
         * para reler e ser arrastado de volta a cada token é o
         * comportamento que se odeia em chat. */
        var observador = new MutationObserver(function () {
            var distanciaDoFim = painel.scrollHeight - painel.scrollTop - painel.clientHeight;
            if (distanciaDoFim < 120) {
                painel.scrollTop = painel.scrollHeight;
            }
        });
        observador.observe(painel, { childList: true, subtree: true, characterData: true });
    }

    /* ------------------------------------------------------- composer */

    var campo = document.getElementById('chat-content');
    var formulario = document.getElementById('nd-chat-form');
    if (campo && formulario) {
        function ajustarAltura() {
            campo.style.height = 'auto';
            campo.style.height = campo.scrollHeight + 'px';
        }
        campo.addEventListener('input', ajustarAltura);
        ajustarAltura();

        campo.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' || event.shiftKey) return;
            /* `isComposing` é o acento morto e o teclado de IME: durante a
             * composição, Enter confirma o caractere. Enviar aí cortaria a
             * palavra no meio — e em português se usa acento o tempo todo. */
            if (event.isComposing || event.keyCode === 229) return;
            if (!campo.value.trim()) {
                event.preventDefault();
                return;
            }
            event.preventDefault();
            if (formulario.requestSubmit) {
                formulario.requestSubmit();
            } else {
                formulario.submit();
            }
        });

        campo.focus();
    }

    /* --------------------------------------------- filtro das conversas */

    var filtro = document.getElementById('nd-chat-filtro');
    if (filtro) {
        filtro.addEventListener('input', function () {
            var termo = filtro.value.trim().toLowerCase();
            document.querySelectorAll('#nd-chat-list [data-nd-busca]').forEach(function (item) {
                var alvo = item.getAttribute('data-nd-busca') || '';
                item.classList.toggle('d-none', termo && alvo.indexOf(termo) === -1);
            });
        });
    }

    /* ------------------------------------------- busca de paciente */

    var buscaPaciente = document.getElementById('nd-chat-paciente');
    var idPaciente = document.getElementById('nd-chat-paciente-id');
    var lista = document.getElementById('nd-chat-paciente-lista');
    if (buscaPaciente && idPaciente && lista) {
        var url = buscaPaciente.getAttribute('data-url');
        var timer = null;
        var geracao = 0;

        function fechar() {
            lista.innerHTML = '';
            lista.classList.add('d-none');
        }

        /* Escapa para texto **e** para atributo.
         *
         * A forma curta -- `div.textContent = t; return div.innerHTML` --
         * escapa `&`, `<` e `>` e **nao** escapa aspas: a serializacao de
         * um no de texto nao sabe em que contexto o resultado sera colado,
         * e aspa so precisa de escape dentro de atributo. Este retorno e
         * colado justamente dentro de um atributo, entao uma aspa dupla no
         * dado fechava o atributo e o que vinha depois virava atributo novo
         * do elemento -- `Maria" onmouseover="...` executava. O nome do
         * paciente e texto livre (`patients/forms.py::clean_full_name` so
         * apara espaco) e nao ha CSP que impeca o manipulador embutido.
         *
         * As duas linhas de `replace` sao o conserto inteiro: com `"` e `'`
         * escapados, o valor nao escapa de atributo de aspa simples nem de
         * aspa dupla, e o contexto de texto continua correto. */
        function escapar(texto) {
            var div = document.createElement('div');
            div.textContent = texto == null ? '' : String(texto);
            return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }

        buscaPaciente.addEventListener('input', function () {
            /* Digitar de novo invalida a escolha anterior: sem isto, trocar
             * o nome depois de escolher deixaria o id do paciente errado no
             * campo oculto, e a conversa nasceria sobre outra pessoa. */
            idPaciente.value = '';
            window.clearTimeout(timer);
            var termo = buscaPaciente.value.trim();
            if (termo.length < 2) {
                fechar();
                return;
            }
            timer = window.setTimeout(function () {
                var minha = ++geracao;
                fetch(url + '?q=' + encodeURIComponent(termo), {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' },
                    credentials: 'same-origin'
                })
                    .then(function (r) { return r.json(); })
                    .then(function (dados) {
                        if (minha !== geracao) return;
                        var linhas = (dados.results || []).slice(0, 8);
                        if (!linhas.length) {
                            lista.innerHTML =
                                '<span class="list-group-item fs-12 text-muted">Nenhum paciente encontrado.</span>';
                            lista.classList.remove('d-none');
                            return;
                        }
                        lista.innerHTML = linhas.map(function (p) {
                            return '<button type="button" class="list-group-item list-group-item-action fs-12" ' +
                                   'data-id="' + escapar(p.id) + '" data-nome="' + escapar(p.full_name) + '">' +
                                   '<span class="fw-semibold">' + escapar(p.full_name) + '</span>' +
                                   (p.record_number ? ' <span class="text-muted">#' + escapar(p.record_number) + '</span>' : '') +
                                   '</button>';
                        }).join('');
                        lista.classList.remove('d-none');
                    })
                    .catch(fechar);
            }, 160);
        });

        lista.addEventListener('click', function (event) {
            var opcao = event.target.closest('[data-id]');
            if (!opcao) return;
            idPaciente.value = opcao.getAttribute('data-id');
            buscaPaciente.value = opcao.getAttribute('data-nome');
            fechar();
        });

        document.addEventListener('click', function (event) {
            if (!lista.contains(event.target) && event.target !== buscaPaciente) fechar();
        });
    }
}());
