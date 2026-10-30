/* Autocomplete de medicamento, da lista da CMED/Anvisa.
 *
 * Um componente para as três telas que precisam dele: o portal público do
 * paciente, a receita do atendimento e a receita avulsa da ficha. São
 * contextos diferentes — um é público e sem sessão, os outros dois estão
 * dentro de `/app/` —, mas a interação é a mesma, e três cópias dela
 * divergiriam na primeira correção.
 *
 * Duas regras que valem mais que o resto:
 *
 * 1. **O campo continua livre.** Isto é uma ajuda para escrever, não um
 *    seletor. Manipulado, fitoterápico, medicamento importado e o que a
 *    lista da CMED não tem continuam sendo digitados à mão — o texto que
 *    vai para a receita é o que está no campo, sempre, tenha vindo da
 *    lista ou não.
 *
 * 2. **A tarja avisa, não decide.** Um item de tarja preta numa receita
 *    simples faz aparecer um aviso com um botão para trocar o formato. A
 *    troca é um clique do médico. A coluna TARJA é atributo da lista de
 *    preços da Anvisa, não o enquadramento da Portaria 344/98, e um
 *    sistema que trocasse o formato sozinho estaria transformando dado
 *    comercial em decisão clínica.
 *
 * Nada aqui usa `innerHTML` com o que volta do servidor: nome comercial e
 * apresentação são texto de terceiro, e entram por `textContent`.
 */
(function () {
    'use strict';

    var MINIMO = 2;
    var ESPERA = 220;

    function criarLista(campo) {
        var lista = document.createElement('div');
        lista.className = 'nd-med-lista';
        lista.hidden = true;
        lista.setAttribute('role', 'listbox');
        campo.parentNode.style.position = 'relative';
        campo.parentNode.appendChild(lista);
        return lista;
    }

    function badgeTarja(item) {
        var badge = document.createElement('span');
        badge.className = 'nd-med-tarja' + (item.controle_especial ? ' is-especial' : '');
        badge.textContent = item.tarja_label;
        return badge;
    }

    function montarOpcao(item, aoEscolher) {
        var opcao = document.createElement('button');
        opcao.type = 'button';
        opcao.className = 'nd-med-opcao';
        opcao.setAttribute('role', 'option');

        var titulo = document.createElement('span');
        titulo.className = 'nd-med-titulo';
        titulo.textContent = item.rotulo;

        var meta = document.createElement('span');
        meta.className = 'nd-med-meta';
        meta.textContent = item.laboratorio || item.substancia;

        opcao.appendChild(titulo);
        opcao.appendChild(meta);
        opcao.appendChild(badgeTarja(item));
        opcao.addEventListener('click', function () { aoEscolher(item); });
        return opcao;
    }

    /* Aviso de tarja. Fica logo abaixo do campo, e some quando o formato
     * muda ou quando o médico o dispensa. */
    function avisar(campo, item, destinoFormato) {
        var anterior = campo.parentNode.querySelector('.nd-med-aviso');
        if (anterior) { anterior.remove(); }
        if (!item.controle_especial) { return; }
        /* Na receita eletrônica do SNCR o formato já é o de controlado, e
         * quem classifica é a lista oficial, não a tarja. */
        if (campo.dataset.ndMedSemAviso) { return; }
        var formato = destinoFormato ? document.getElementById(destinoFormato) : null;
        /* Já está em controle especial: não há o que avisar. */
        if (formato && formato.value === 'special_control') { return; }

        var caixa = document.createElement('div');
        caixa.className = 'nd-med-aviso';
        var texto = document.createElement('span');
        texto.textContent = item.tarja_label + ' na lista da CMED. Medicamentos assim '
            + 'costumam exigir Receituário de Controle Especial.';
        caixa.appendChild(texto);

        if (formato) {
            var trocar = document.createElement('button');
            trocar.type = 'button';
            trocar.className = 'btn btn-sm btn-light-warning ms-2';
            trocar.textContent = 'Trocar para controle especial';
            trocar.addEventListener('click', function () {
                formato.value = 'special_control';
                formato.dispatchEvent(new Event('change', { bubbles: true }));
                caixa.remove();
            });
            caixa.appendChild(trocar);
        }
        var manter = document.createElement('button');
        manter.type = 'button';
        manter.className = 'btn btn-sm btn-link text-muted';
        manter.textContent = 'Dispensar';
        manter.addEventListener('click', function () { caixa.remove(); });
        caixa.appendChild(manter);

        campo.parentNode.appendChild(caixa);
    }

    function ligar(campo) {
        var url = campo.dataset.ndMedUrl;
        if (!url) { return; }
        var lista = criarLista(campo);
        var relogio = null;

        function fechar() { lista.hidden = true; lista.textContent = ''; }

        /* Resolve um destino declarado no HTML.
         *
         * Um id serve quando o campo é único na tela (a receita). Não serve
         * no portal, onde a linha de medicação é CLONADA para acrescentar
         * outra: ids repetidos fazem `getElementById` devolver sempre o
         * primeiro, e a segunda linha passaria a preencher a dose da
         * primeira. Por isso um valor que comece com `[` ou `.` é tratado
         * como seletor procurado DENTRO do grupo daquela linha. */
        function destino(valor) {
            if (!valor) { return null; }
            if (valor.charAt(0) === '[' || valor.charAt(0) === '.') {
                var grupo = campo.closest('[data-nd-med-grupo]') || campo.parentNode.parentNode;
                return grupo ? grupo.querySelector(valor) : null;
            }
            return document.getElementById(valor);
        }

        /* Acrescenta uma linha ao fim da prescrição, sem apagar o que já
         * estava escrito, e esvazia a busca.
         *
         * Serve aos dois caminhos: o item escolhido da lista e o termo que
         * a lista não tem. O segundo existe porque a falta dele era uma
         * armadilha — ver `semResultado`. */
        function acrescentarNaReceita(alvoTexto, texto) {
            var atual = alvoTexto.value.replace(/\s+$/, '');
            alvoTexto.value = (atual ? atual + '\n' : '') + texto + '\n';
            alvoTexto.dispatchEvent(new Event('input', { bubbles: true }));
            campo.value = '';
        }

        function escolher(item) {
            /* Para onde vai o que foi escolhido. Três destinos possíveis,
             * declarados no HTML — o componente não sabe de tela nenhuma. */
            var alvoDose = destino(campo.dataset.ndMedDose);
            var alvoTexto = destino(campo.dataset.ndMedTexto);

            if (alvoTexto) {
                acrescentarNaReceita(alvoTexto, item.rotulo);
            } else if (alvoDose) {
                /* Portal: nome num campo, concentração no outro. A
                 * apresentação integral da CMED inclui blister, material e
                 * tamanho da caixa, que não são a dose pedida aqui.
                 *
                 * Receita eletrônica do SNCR (`data-nd-med-nome="substancia"`):
                 * a substância (DCB), que é o que a lista oficial classifica,
                 * e a forma farmacêutica por extenso no campo dela. */
                campo.value = campo.dataset.ndMedNome === 'substancia'
                    ? (item.substancia || item.produto) : (item.produto || item.substancia);
                alvoDose.value = item.dosagem || item.apresentacao;
                var alvoForma = destino(campo.dataset.ndMedForma);
                if (alvoForma && item.forma) { alvoForma.value = item.forma; }
            } else {
                campo.value = item.rotulo;
            }
            avisar(campo, item, campo.dataset.ndMedFormato);
            fechar();
        }

        /* O que aparece quando a CMED não tem o termo.
         *
         * Era só uma frase: "pode escrever à mão, o campo aceita". A frase
         * está certa e a armadilha era outra: **este** campo não tem `name`
         * e não é enviado com o formulário. Quem lia "o campo aceita" como
         * "este campo aceita" digitava o remédio aqui, escrevia a posologia
         * no campo de baixo e enviava — e saía uma receita de controle
         * especial assinada com "1 cp VO a noite" e sem o medicamento.
         * Relatado em 2026-09-25, com o PDF.
         *
         * Agora o estado vazio é uma AÇÃO: um botão que leva o que foi
         * digitado para a prescrição, que é o campo que existe de verdade.
         * O caminho que o médico já tentava seguir passa a funcionar, em
         * vez de terminar em silêncio. */
        function semResultado(termo) {
            var caixa = document.createElement('div');
            caixa.className = 'nd-med-vazio';

            var frase = document.createElement('span');
            frase.textContent = 'Nada na lista da CMED com esse termo.';
            caixa.appendChild(frase);

            var alvoTexto = destino(campo.dataset.ndMedTexto);
            if (!alvoTexto) {
                /* Portal do paciente: ali o campo de busca É o campo do
                 * pedido, e o que foi digitado já está onde precisa. */
                frase.textContent += ' Pode deixar escrito como está.';
                return caixa;
            }

            var usar = document.createElement('button');
            usar.type = 'button';
            usar.className = 'btn btn-sm btn-light-primary ms-2';
            /* `textContent` e não `innerHTML`: o termo é o que o usuário
             * digitou, e a regra do arquivo vale também para ele. */
            usar.textContent = 'Usar “' + termo + '” assim mesmo';
            usar.addEventListener('click', function () {
                acrescentarNaReceita(alvoTexto, termo);
                fechar();
                alvoTexto.focus();
            });
            caixa.appendChild(usar);
            return caixa;
        }

        function buscar() {
            var termo = campo.value.trim();
            if (termo.length < MINIMO) { fechar(); return; }
            fetch(url + '?q=' + encodeURIComponent(termo), {
                headers: { 'Accept': 'application/json' },
            }).then(function (r) {
                if (!r.ok) { throw new Error('busca indisponível'); }
                return r.json();
            }).then(function (dados) {
                lista.textContent = '';
                if (!dados.results.length) {
                    lista.appendChild(semResultado(termo));
                } else {
                    dados.results.forEach(function (item) {
                        lista.appendChild(montarOpcao(item, escolher));
                    });
                }
                lista.hidden = false;
            }).catch(function () {
                /* Catálogo fora do ar não pode impedir de prescrever: a
                 * lista simplesmente não aparece e o campo segue livre. */
                fechar();
            });
        }

        campo.setAttribute('autocomplete', 'off');
        campo.addEventListener('input', function () {
            window.clearTimeout(relogio);
            relogio = window.setTimeout(buscar, ESPERA);
        });
        campo.addEventListener('keydown', function (evento) {
            if (evento.key === 'Escape') { fechar(); }
        });
        document.addEventListener('click', function (evento) {
            if (!campo.parentNode.contains(evento.target)) { fechar(); }
        });
    }

    function ligarTodos(raiz) {
        (raiz || document).querySelectorAll('[data-nd-med-url]').forEach(function (campo) {
            /* Marca o campo: uma linha clonada traz o atributo junto, e
             * ligar duas vezes daria duas listas sobrepostas. */
            if (campo.dataset.ndMedLigado) { return; }
            campo.dataset.ndMedLigado = '1';
            ligar(campo);
        });
    }

    /* Exposto porque a tela que CLONA a linha de medicação (o portal)
     * precisa ligar o campo novo. Um `MutationObserver` global resolveria
     * sozinho, e ficaria observando o documento inteiro para atender um
     * caso só. */
    window.ndMedicamentos = { ligar: ligarTodos };

    ligarTodos(document);
})();
