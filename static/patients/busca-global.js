/*
 * Busca rápida de paciente (Ctrl+K / ⌘K).
 *
 * A secretária passa o dia entre a ligação que chega e a pessoa no balcão,
 * e o caminho até a ficha de um paciente era sempre o mesmo: menu lateral,
 * Pacientes, campo de busca, Enter. Quatro passos para uma pergunta que se
 * responde com o nome. Isto encurta para dois — o atalho e o nome.
 *
 * Nada aqui decide o que pode ser visto. A lista vem de
 * `patients.views.PatientGlobalSearchView`, que nasce de `scope_to_tenant`:
 * paciente de outra clínica não chega até aqui, e não haveria como filtrar
 * no navegador se chegasse.
 *
 * Sem `innerHTML` em dado vindo do servidor. Nome de paciente é texto que
 * outra pessoa digitou, e o dia em que alguém se chamar `<img onerror=...>`
 * não pode ser o dia em que se descobre isso.
 */
(function () {
    'use strict';

    var ESPERA_MS = 200;
    var MINIMO = 2;

    var overlay = document.getElementById('nd-busca');
    if (!overlay) { return; }

    var campo = document.getElementById('nd-busca-campo');
    var lista = document.getElementById('nd-busca-resultados');
    var estado = document.getElementById('nd-busca-estado');
    var fechar = document.getElementById('nd-busca-fechar');
    var url = overlay.getAttribute('data-nd-busca-url');

    var temporizador = null;
    var requisicao = 0;
    var ativo = -1;
    var itens = [];
    var focoAnterior = null;

    function dizer(texto) {
        estado.textContent = texto;
        estado.hidden = !texto;
    }

    function limparLista() {
        lista.textContent = '';
        itens = [];
        ativo = -1;
        campo.setAttribute('aria-expanded', 'false');
    }

    function abrir() {
        if (!overlay.hidden) { return; }
        focoAnterior = document.activeElement;
        overlay.hidden = false;
        campo.value = '';
        limparLista();
        dizer('Digite ao menos ' + MINIMO + ' caracteres.');
        campo.focus();
    }

    function fecharBusca() {
        if (overlay.hidden) { return; }
        overlay.hidden = true;
        limparLista();
        window.clearTimeout(temporizador);
        /* Devolve o foco a quem o tinha. Sem isto, quem abriu a busca pelo
         * teclado no meio de um formulário volta para o começo da página. */
        if (focoAnterior && document.contains(focoAnterior)) {
            focoAnterior.focus();
        }
        focoAnterior = null;
    }

    function marcar(indice) {
        if (!itens.length) { return; }
        /* Circular: de baixo volta ao topo. Seis resultados são poucos, e
         * quem passa do último quer o primeiro, não parar. */
        if (indice < 0) { indice = itens.length - 1; }
        if (indice >= itens.length) { indice = 0; }
        itens.forEach(function (li, i) {
            li.classList.toggle('is-ativo', i === indice);
            li.setAttribute('aria-selected', i === indice ? 'true' : 'false');
        });
        ativo = indice;
        itens[indice].scrollIntoView({ block: 'nearest' });
    }

    function montar(resultados) {
        limparLista();
        if (!resultados.length) {
            dizer('Nenhum paciente encontrado.');
            return;
        }
        dizer('');
        resultados.forEach(function (p) {
            var li = document.createElement('li');
            li.setAttribute('role', 'option');
            li.setAttribute('aria-selected', 'false');

            var a = document.createElement('a');
            a.href = p.url;

            var nome = document.createElement('span');
            nome.className = 'd-block fs-13 fw-semibold text-dark';
            nome.textContent = p.nome;

            /* Uma linha só com o que distingue dois homônimos: nascimento,
             * CPF mascarado e o número do prontuário. É o que a secretária
             * confere em voz alta ao telefone. */
            var detalhe = document.createElement('span');
            detalhe.className = 'd-block fs-11 text-muted';
            detalhe.textContent = [
                p.nascimento ? 'Nasc. ' + p.nascimento : '',
                p.cpf_mascarado ? 'CPF ' + p.cpf_mascarado : '',
                p.prontuario ? 'Prontuário ' + p.prontuario : ''
            ].filter(Boolean).join(' · ');

            a.appendChild(nome);
            a.appendChild(detalhe);
            li.appendChild(a);
            lista.appendChild(li);
            itens.push(li);
        });
        campo.setAttribute('aria-expanded', 'true');
        marcar(0);
    }

    function buscar(termo) {
        var meu = ++requisicao;
        fetch(url + '?q=' + encodeURIComponent(termo), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin'
        }).then(function (r) {
            if (!r.ok) { throw new Error('busca falhou: ' + r.status); }
            return r.json();
        }).then(function (dados) {
            /* Resposta atrasada de uma digitação anterior não pode
             * sobrescrever a lista da digitação atual. */
            if (meu !== requisicao || overlay.hidden) { return; }
            montar(dados.resultados || []);
        }).catch(function () {
            if (meu !== requisicao) { return; }
            limparLista();
            dizer('Não deu para buscar agora. Tente de novo.');
        });
    }

    campo.addEventListener('input', function () {
        var termo = campo.value.trim();
        window.clearTimeout(temporizador);
        if (termo.length < MINIMO) {
            limparLista();
            dizer('Digite ao menos ' + MINIMO + ' caracteres.');
            return;
        }
        dizer('Procurando…');
        temporizador = window.setTimeout(function () { buscar(termo); }, ESPERA_MS);
    });

    campo.addEventListener('keydown', function (event) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            marcar(ativo + 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            marcar(ativo - 1);
        } else if (event.key === 'Enter') {
            if (ativo >= 0 && itens[ativo]) {
                event.preventDefault();
                itens[ativo].querySelector('a').click();
            }
        }
    });

    overlay.addEventListener('click', function (event) {
        /* Clique no fundo fecha; clique na caixa, não. */
        if (event.target === overlay) { fecharBusca(); }
    });

    if (fechar) { fechar.addEventListener('click', fecharBusca); }

    document.addEventListener('keydown', function (event) {
        var tecla = (event.key || '').toLowerCase();
        if (tecla === 'k' && (event.ctrlKey || event.metaKey) && !event.altKey) {
            /* `preventDefault` antes de qualquer coisa: Ctrl+K é a barra de
             * endereços em alguns navegadores, e abrir a busca do NeuroDoc
             * junto com a do navegador seria pior que não ter atalho. */
            event.preventDefault();
            if (overlay.hidden) { abrir(); } else { fecharBusca(); }
            return;
        }
        if (event.key === 'Escape' && !overlay.hidden) {
            event.preventDefault();
            fecharBusca();
        }
    });

    document.addEventListener('click', function (event) {
        var gatilho = event.target.closest('[data-nd-busca-abrir]');
        if (!gatilho) { return; }
        event.preventDefault();
        abrir();
    });
})();
