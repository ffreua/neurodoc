/* Janela de mensagens da equipe: abrir, arrastar, redimensionar, conversar.
 *
 * Três decisões que explicam o resto do arquivo:
 *
 * 1. **Nada de `innerHTML` com texto de usuário.** Todo nome e toda
 *    mensagem entram por `textContent`. É a mesma regra do chat de IA
 *    (`static/ai/chat.js`), e aqui vale ainda mais: lá o texto vinha do
 *    modelo, aqui vem de um colega que pode colar qualquer coisa. O
 *    servidor devolve JSON justamente para que o cliente nunca precise
 *    montar marcação com conteúdo alheio.
 *
 * 2. **O SSE fica aberto enquanto a página existe, em UMA aba só.** A
 *    badge tem de acender no instante em que o colega escreve, e o caso
 *    que importa é o da janela fechada. Um stream por aba estouraria o
 *    limite de seis conexões por origem do HTTP/1.1, então as abas elegem
 *    uma líder e o que chega é repassado pelo `BroadcastChannel` — ver
 *    "liderança entre abas". A sondagem virou rede de segurança.
 *
 * 3. **Posição e tamanho são preferência do usuário**, gravados no
 *    `localStorage` e reaplicados a cada página — o produto é SSR, então a
 *    janela é recriada a cada navegação, e uma janela que volta ao canto
 *    inferior direito toda vez que se abre um paciente seria inútil.
 */
(function () {
    'use strict';

    var raiz = document.getElementById('nd-teamchat');
    var botao = document.getElementById('nd-tc-toggle');
    if (!raiz || !botao) { return; }

    var janela = raiz.querySelector('.nd-tc-win');
    var badge = document.getElementById('nd-tc-badge');
    var listaPessoas = document.getElementById('nd-tc-pessoas');
    var filtro = document.getElementById('nd-tc-filtro');
    var painelMsgs = document.getElementById('nd-tc-msgs');
    var blocoVazio = document.getElementById('nd-tc-vazio');
    var blocoConversa = document.getElementById('nd-tc-conversa');
    var rotuloQuem = document.getElementById('nd-tc-quem');
    var rotuloPapeis = document.getElementById('nd-tc-papeis');
    var formulario = document.getElementById('nd-tc-form');
    var campo = document.getElementById('nd-tc-texto');
    var erro = document.getElementById('nd-tc-erro');
    var barra = document.getElementById('nd-tc-bar');
    var alca = document.getElementById('nd-tc-grip');

    /* A sondagem virou rede de segurança, não o canal principal: quem
     * entrega a mensagem é o SSE, que agora fica aberto mesmo com a janela
     * fechada (ver "liderança entre abas"). Ela existe para reconciliar
     * contadores e presença depois de uma queda de conexão. */
    var POLL_SEGUNDOS = 30;
    var UUID_MOLDE = '00000000-0000-0000-0000-000000000000';
    var CHAVE_GEOMETRIA = 'nd-tc-geometria';
    var CHAVE_ABERTA = 'nd-tc-aberta';
    var CHAVE_LIDER = 'nd-tc-lider';
    var MARGEM_VISIVEL = 80;
    /* Aluguel da liderança: renovado a cada `LIDER_RENOVA`, considerado
     * abandonado depois de `LIDER_VENCE`. A folga de três renovações
     * absorve a aba em segundo plano, cujos temporizadores o navegador
     * estica para um por minuto — sem ela, duas abas ficariam disputando a
     * liderança a cada troca de aba. */
    var LIDER_RENOVA = 3000;
    var LIDER_VENCE = 70000;

    var eu = raiz.dataset.eu;
    var pessoas = [];
    var pessoaAtual = null;
    var conversaAtual = '';
    /* Ids já desenhados. O próprio remetente recebe o evento da mensagem
     * que acabou de enviar (ver `services._announce`), e a segunda aba da
     * mesma pessoa também — sem este conjunto, a linha apareceria duas
     * vezes na aba que a escreveu. */
    var vistas = Object.create(null);
    /* Ids ja CONTADOS na badge. Separado de `vistas` porque os dois tem
     * tempos de vida diferentes: `vistas` e zerado a cada conversa aberta,
     * para que reabrir uma conversa a desenhe de novo, e zerar o contador
     * junto faria uma mensagem antiga reentregue voltar a somar. */
    var contadas = Object.create(null);
    var quantasContadas = 0;
    var ultimoDia = '';
    var fonte = null;
    var relogio = null;
    var relogioLider = null;
    /* Quantas não lidas a badge mostra. Guardado em variável, e não lido do
     * DOM, porque ele sobe de duas fontes: a sondagem, que traz o número
     * autoritativo, e cada evento que chega, que soma um na hora. */
    var totalNaoLidas = Number(badge && badge.textContent) || 0;
    var tituloOriginal = document.title;
    var meuId = String(Date.now()) + Math.random().toString(36).slice(2);
    /* Um canal entre as abas deste navegador. Quando falta (navegador
     * antigo), cada aba vira líder de si mesma: volta ao comportamento de
     * uma conexão por aba, que funciona — só gasta mais conexões. */
    var canal = ('BroadcastChannel' in window) ? new BroadcastChannel('nd-teamchat') : null;
    var reconciliar = null;

    /* ------------------------------------------------------------ rede */

    /* O token de CSRF vem do **cookie**, lido na hora do envio — e só cai no
     * campo escondido se o cookie não existir.
     *
     * O campo é gravado quando a página é montada e envelhece: o Django
     * troca o token a cada login, e uma aba aberta antes de alguém entrar
     * com outra conta no mesmo navegador fica com o token anterior. O
     * envio entao volta 403, e era isso que acontecia — uma aba mandava e a
     * outra nao. O cookie e sempre o da sessao atual. */
    function token() {
        var doCookie = (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/) || [])[1];
        if (doCookie) { return decodeURIComponent(doCookie); }
        var campoCsrf = raiz.querySelector('input[name="csrfmiddlewaretoken"]');
        return campoCsrf ? campoCsrf.value : '';
    }

    function endereco(molde, id) {
        return molde.replace(UUID_MOLDE, id);
    }

    function pedir(url, corpo) {
        var opcoes = { headers: { 'Accept': 'application/json' } };
        if (corpo !== undefined) {
            opcoes.method = 'POST';
            opcoes.headers['Content-Type'] = 'application/json';
            opcoes.headers['X-CSRFToken'] = token();
            opcoes.body = JSON.stringify(corpo);
        }
        return fetch(url, opcoes).then(function (resposta) {
            var tipo = resposta.headers.get('Content-Type') || '';
            if (tipo.indexOf('application/json') === -1) {
                /* Resposta em HTML onde se esperava JSON: ou o Django
                 * recusou o CSRF (403 com a página de erro dele), ou a
                 * clínica foi suspensa depois que esta página carregou, ou
                 * a sessão acabou e veio a tela de login.
                 *
                 * A versão anterior afirmava "organização suspensa" em todo
                 * 403, e afirmava errado: a causa comum é o token de CSRF,
                 * e a suspensão nem sequer renderiza o campo de escrever.
                 * Nomear a causa errada manda a pessoa procurar problema no
                 * lugar em que ele não está — o texto agora diz o que fazer,
                 * que é o mesmo nos três casos. */
                throw new Error(resposta.status === 403
                    ? 'A sessão desta aba mudou (ou a organização foi suspensa). Recarregue a página.'
                    : 'Sessão encerrada. Recarregue a página.');
            }
            return resposta.json().then(function (dados) {
                if (!resposta.ok) {
                    throw new Error(dados.erro || 'Não foi possível completar a ação.');
                }
                return dados;
            });
        });
    }

    function avisarErro(mensagem) {
        if (!erro) { return; }
        erro.textContent = mensagem;
        erro.hidden = false;
    }

    function limparErro() {
        if (erro) { erro.hidden = true; }
    }

    /* -------------------------------------------------------- cabeçalho */

    /* A badge é o aviso de que alguém está tentando falar com você, e na
     * maior parte do tempo a janela está fechada e a aba está atrás de
     * outra. Por isso são três sinais e não um:
     *
     *   o número no círculo vermelho, para quem está olhando a tela;
     *   um pulso curto quando ele cresce, para o canto do olho perceber;
     *   e `(3)` no título da aba, que é o único que atravessa uma aba em
     *   segundo plano — é onde se olha para saber se chegou alguma coisa
     *   sem trocar de aba. */
    function atualizarBadge(total) {
        var cresceu = total > totalNaoLidas;
        totalNaoLidas = total;
        if (badge) {
            badge.textContent = total;
            badge.hidden = !total;
            if (cresceu) { pulsar(); }
        }
        document.title = total ? '(' + total + ') ' + tituloOriginal : tituloOriginal;
    }

    function pulsar() {
        if (!badge) { return; }
        /* Reinicia a animação: sem remover a classe e forçar o
         * recálculo, duas mensagens seguidas pulsam uma vez só. */
        badge.classList.remove('is-nova');
        void badge.offsetWidth;
        badge.classList.add('is-nova');
    }

    /* Recontagem autoritativa, pedida ao servidor com um atraso curto.
     *
     * Existe para o primeiro contato: quando a mensagem vem de alguém com
     * quem nunca se conversou, a aba ainda não conhece o id daquela
     * conversa, então soma no total mas não sabe em quem marcar. Uma volta
     * ao servidor resolve — com atraso, porque cinco mensagens seguidas de
     * um colega apressado não podem virar cinco recontagens. */
    function reconciliarEmBreve() {
        window.clearTimeout(reconciliar);
        reconciliar = window.setTimeout(carregarEstado, 1200);
    }

    function totalLocal() {
        return pessoas.reduce(function (soma, p) { return soma + p.nao_lidas; }, 0);
    }

    /* ---------------------------------------------------------- pessoas */

    function desenharPessoas() {
        var procurado = (filtro && filtro.value || '').trim().toLowerCase();
        listaPessoas.textContent = '';
        var mostradas = 0;

        pessoas.forEach(function (pessoa) {
            if (procurado && pessoa.nome.toLowerCase().indexOf(procurado) === -1) { return; }
            mostradas += 1;

            var item = document.createElement('li');
            var alvo = document.createElement('button');
            alvo.type = 'button';
            alvo.className = 'nd-tc-pessoa' + (pessoa.online ? ' is-online' : '')
                + (pessoaAtual && pessoaAtual.user_id === pessoa.user_id ? ' is-ativa' : '');

            var ponto = document.createElement('span');
            ponto.className = 'nd-tc-ponto';
            /* A bolinha é cor; quem usa leitor de tela precisa da palavra. */
            ponto.setAttribute('role', 'img');
            ponto.setAttribute('aria-label', pessoa.online ? 'on-line' : 'off-line');

            var textos = document.createElement('span');
            var nome = document.createElement('span');
            nome.className = 'nd-tc-nome';
            nome.textContent = pessoa.nome;
            var papel = document.createElement('span');
            papel.className = 'nd-tc-papel';
            papel.textContent = pessoa.papeis.join(' · ');
            textos.appendChild(nome);
            textos.appendChild(papel);

            alvo.appendChild(ponto);
            alvo.appendChild(textos);

            if (pessoa.nao_lidas) {
                var contador = document.createElement('span');
                contador.className = 'nd-tc-nao-lidas';
                contador.textContent = pessoa.nao_lidas;
                contador.setAttribute('aria-label', pessoa.nao_lidas + ' mensagem(ns) não lida(s)');
                alvo.appendChild(contador);
            }

            alvo.addEventListener('click', function () { selecionar(pessoa); });
            item.appendChild(alvo);
            listaPessoas.appendChild(item);
        });

        if (!mostradas) {
            var vazio = document.createElement('li');
            vazio.className = 'nd-tc-papel p-3';
            vazio.textContent = procurado
                ? 'Ninguém com esse nome.'
                : 'Você é a única pessoa com vínculo ativo nesta organização.';
            listaPessoas.appendChild(vazio);
        }
    }

    /* A aba entrou como uma pessoa e a sessão do navegador virou de outra.
     *
     * Acontece o tempo todo em teste e acontece na clínica: duas abas do
     * mesmo perfil dividem UM cookie, então entrar com outra conta na
     * segunda aba troca a sessão da primeira também. A aba antiga continua
     * mostrando o nome de quem entrou nela, mas passa a falar pelo servidor
     * como a conta nova — e a lista de colegas some a pessoa errada e
     * mantém a errada, sem nenhum aviso.
     *
     * A tela para de adivinhar e diz o que houve. Nada de recarregar
     * sozinha: a pessoa pode ter um formulário preenchido embaixo. */
    function sessaoTrocada() {
        desconectar();
        window.clearInterval(relogio);
        atualizarBadge(0);
        raiz.hidden = false;
        botao.setAttribute('aria-expanded', 'true');
        blocoConversa.hidden = true;
        blocoVazio.hidden = false;
        listaPessoas.textContent = '';
        blocoVazio.textContent = '';
        var titulo = document.createElement('p');
        titulo.className = 'fw-semibold mb-1';
        titulo.textContent = 'Esta aba não é mais a sua sessão';
        var texto = document.createElement('p');
        texto.className = 'fs-11 text-muted mb-0';
        texto.textContent = 'Alguém entrou com outra conta neste navegador, e as '
            + 'abas compartilham a mesma sessão. Recarregue a página para continuar '
            + 'com a conta que está ativa agora.';
        blocoVazio.appendChild(titulo);
        blocoVazio.appendChild(texto);
    }

    function carregarEstado() {
        return pedir(raiz.dataset.urlEstado).then(function (dados) {
            if (dados.eu !== eu) { sessaoTrocada(); return; }
            pessoas = dados.pessoas;
            atualizarBadge(dados.total);
            desenharPessoas();
        }).catch(function () {
            /* Falha de rede numa sondagem de fundo não vira aviso na tela:
             * a próxima volta resolve, e um alerta a cada oscilação de
             * conexão treinaria a equipe a ignorar avisos. */
        });
    }

    /* --------------------------------------------------------- conversa */

    /* Trocar de pessoa **zera** a conversa corrente antes de pedir a nova, e
     * toda resposta atrasada é descartada por um número de pedido.
     *
     * As duas coisas consertam o mesmo defeito, que é o pior que este
     * arquivo podia ter: se abrir a conversa falhasse (rede caída, 400),
     * `conversaAtual` continuava apontando para a conversa **anterior**
     * enquanto o cabeçalho já mostrava o novo nome — escrever ali mandaria
     * a mensagem para a pessoa errada. O mesmo valia para o clique rápido
     * em duas pessoas: a resposta lenta da primeira chegava depois e
     * sobrescrevia a conversa da segunda.
     *
     * Num sistema em que se escreve "a paciente das 15h piorou", mandar
     * para o colega errado não é um incômodo de interface. */
    var pedidoAtual = 0;

    function selecionar(pessoa) {
        limparErro();
        pedidoAtual += 1;
        var meuPedido = pedidoAtual;
        pessoaAtual = pessoa;
        conversaAtual = '';
        rotuloQuem.textContent = pessoa.nome;
        rotuloPapeis.textContent = pessoa.papeis.join(' · ');
        blocoVazio.hidden = true;
        blocoConversa.hidden = false;
        painelMsgs.textContent = '';
        vistas = Object.create(null);
        ultimoDia = '';
        janela.classList.add('is-conversa');
        botaoVoltar(celular());
        desenharPessoas();

        var promessa = pessoa.conversa
            ? Promise.resolve({ conversa: pessoa.conversa })
            : pedir(raiz.dataset.urlAbrir, { user_id: pessoa.user_id });

        promessa.then(function (dados) {
            if (meuPedido !== pedidoAtual) { return null; }
            conversaAtual = dados.conversa;
            pessoa.conversa = dados.conversa;
            return pedir(endereco(raiz.dataset.urlConversa, dados.conversa));
        }).then(function (dados) {
            if (dados === null || meuPedido !== pedidoAtual) { return null; }
            dados.mensagens.forEach(function (m) { desenharMensagem(m, false); });
            aoFim();
            return marcarLida();
        }).then(function () {
            if (meuPedido === pedidoAtual && campo) { campo.focus(); }
        }).catch(function (e) {
            if (meuPedido !== pedidoAtual) { return; }
            /* Sem conversa aberta não há para onde escrever, e é isso que
             * o `conversaAtual = ''` acima garante. */
            avisarErro(e.message + ' Escolha a pessoa de novo.');
        });
    }

    function marcarLida() {
        if (!conversaAtual) { return Promise.resolve(); }
        var conversa = conversaAtual;
        return pedir(endereco(raiz.dataset.urlLida, conversa), {}).then(function (dados) {
            atualizarBadge(dados.total);
            pessoas.forEach(function (p) {
                if (p.conversa === conversa) { p.nao_lidas = 0; }
            });
            desenharPessoas();
            /* As outras abas desta pessoa mostram a mesma badge e não têm
             * como saber que a conversa foi lida aqui. */
            if (canal) { canal.postMessage({ tipo: 'lida', total: dados.total }); }
        }).catch(function () { /* a próxima sondagem reconcilia */ });
    }

    function desenharMensagem(m, rolar) {
        if (vistas[m.id]) { return; }
        vistas[m.id] = true;

        /* Medido **antes** de acrescentar qualquer coisa ao painel: quem
         * rolou para trás para reler não pode ser arrastado de volta para
         * o fim a cada mensagem que chega. É o comportamento que se odeia
         * em chat, e depois do `appendChild` a medida já estaria errada. */
        var colado = painelMsgs.scrollHeight - painelMsgs.scrollTop - painelMsgs.clientHeight < 120;

        var quando = new Date(m.em);
        var dia = quando.toLocaleDateString('pt-BR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
        });
        if (dia !== ultimoDia) {
            ultimoDia = dia;
            var separador = document.createElement('span');
            separador.className = 'nd-tc-dia';
            separador.textContent = dia === new Date().toLocaleDateString('pt-BR', {
                day: '2-digit', month: '2-digit', year: 'numeric',
            }) ? 'hoje' : dia;
            painelMsgs.appendChild(separador);
        }

        var bolha = document.createElement('div');
        bolha.className = 'nd-tc-msg' + (m.de === eu ? ' is-minha' : '');
        /* `textContent`, sempre. O CSS faz `white-space: pre-wrap`, então
         * a quebra de linha que a pessoa digitou aparece sem que uma única
         * marcação venha do texto. */
        bolha.textContent = m.texto;

        var meta = document.createElement('span');
        meta.className = 'nd-tc-msg-meta';
        meta.textContent = (m.de === eu ? 'você' : m.nome) + ' · '
            + quando.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
        bolha.appendChild(meta);

        painelMsgs.appendChild(bolha);
        if (rolar && colado) { aoFim(); }
    }

    function aoFim() {
        painelMsgs.scrollTop = painelMsgs.scrollHeight;
    }

    /* ----------------------------------------------------------- envio */

    if (formulario) {
        formulario.addEventListener('submit', function (evento) {
            evento.preventDefault();
            var texto = campo.value.trim();
            if (!texto) { return; }
            if (!conversaAtual) {
                /* Acontece quando abrir a conversa falhou: o cabeçalho
                 * mostra o nome, mas não há conversa. Melhor dizer do que
                 * engolir o Enter em silêncio. */
                avisarErro('A conversa não abriu. Escolha a pessoa de novo na lista.');
                return;
            }
            limparErro();
            /* O campo é limpo antes da resposta: quem escreveu já seguiu
             * para a próxima frase. Se o envio falhar, o texto volta para
             * o campo — perder o que foi digitado é o pior desfecho
             * possível aqui. */
            campo.value = '';
            ajustarAltura();
            pedir(endereco(raiz.dataset.urlEnviar, conversaAtual), { texto: texto })
                .then(function (dados) {
                    desenharMensagem(dados.mensagem, true);
                    aoFim();
                })
                .catch(function (e) {
                    campo.value = texto;
                    ajustarAltura();
                    avisarErro(e.message);
                });
        });
    }

    function ajustarAltura() {
        if (!campo) { return; }
        campo.style.height = 'auto';
        campo.style.height = Math.min(campo.scrollHeight, 120) + 'px';
    }

    if (campo) {
        campo.addEventListener('input', ajustarAltura);
        campo.addEventListener('keydown', function (evento) {
            if (evento.key !== 'Enter' || evento.shiftKey) { return; }
            /* `isComposing` é o acento morto: durante a composição, Enter
             * confirma o caractere. Enviar aí cortaria a palavra no meio —
             * e em português se usa acento o tempo todo. */
            if (evento.isComposing || evento.keyCode === 229) { return; }
            evento.preventDefault();
            if (formulario.requestSubmit) { formulario.requestSubmit(); }
        });
    }

    if (filtro) {
        filtro.addEventListener('input', desenharPessoas);
    }

    /* ---------------------------------------------- SSE e o que fazer com ele */

    /* O que uma mensagem que chega provoca — venha ela do SSE desta aba ou
     * do canal de outra aba deste navegador. */
    function aplicarMensagem(m) {
        /* Cada mensagem conta uma vez so, venha por onde vier.
         *
         * Sem esta trava a badge inflava: o `EventSource` reconecta sozinho
         * e pode reentregar o ultimo evento, e numa disputa de lideranca a
         * mesma mensagem chega pelo stream desta aba e pelo canal da outra.
         * A sondagem corrigia o numero 1,2 s depois, mas nesse intervalo a
         * pessoa lia "4" onde havia 3 — e um contador que se contradiz e um
         * contador em que ninguem confia.
         *
         * O teto existe para a aba deixada aberta o dia inteiro; estourado,
         * zera e a recontagem do servidor devolve a verdade. */
        if (contadas[m.id]) { return; }
        contadas[m.id] = true;
        quantasContadas += 1;
        if (quantasContadas > 1000) { contadas = Object.create(null); quantasContadas = 0; }

        if (m.conversa === conversaAtual) {
            desenharMensagem(m, true);
            if (m.de !== eu) { marcarLida(); }
            return;
        }
        /* Eco da própria mensagem, mandado para as outras abas desta
         * pessoa: não conta como não lida em lugar nenhum. */
        if (m.de === eu) { return; }

        /* Soma um no total antes de saber de quem é. O caso que obriga a
         * isso é justamente o mais importante: a primeira mensagem de um
         * colega com quem nunca se conversou chega numa conversa que esta
         * aba ainda não conhece — contar só o que está na lista deixaria a
         * badge apagada exatamente quando alguém está tentando contato. */
        atualizarBadge(totalNaoLidas + 1);
        pessoas.forEach(function (p) {
            if (p.conversa === m.conversa) { p.nao_lidas += 1; }
        });
        desenharPessoas();
        reconciliarEmBreve();
    }

    function conectar() {
        if (fonte || !window.EventSource) { return; }
        fonte = new EventSource(raiz.dataset.urlStream);
        fonte.addEventListener('mensagem', function (evento) {
            var m = JSON.parse(evento.data);
            aplicarMensagem(m);
            /* Repassa às outras abas: só esta tem o stream aberto. */
            if (canal) { canal.postMessage({ tipo: 'mensagem', m: m }); }
        });
        fonte.addEventListener('revogado', function () {
            desconectar();
            if (canal) { canal.postMessage({ tipo: 'revogado' }); }
            avisarErro('Seu vínculo com esta organização mudou. Recarregue a página.');
        });
        /* Erro de conexão não fecha a fonte: `EventSource` reconecta
         * sozinho com o `Last-Event-ID`, que é a razão de usá-lo em vez de
         * um laço de `fetch` escrito à mão. */
    }

    function desconectar() {
        if (fonte) { fonte.close(); fonte = null; }
    }

    if (canal) {
        canal.onmessage = function (evento) {
            var dado = evento.data || {};
            if (dado.tipo === 'mensagem') { aplicarMensagem(dado.m); }
            if (dado.tipo === 'revogado') {
                desconectar();
                avisarErro('Seu vínculo com esta organização mudou. Recarregue a página.');
            }
            /* Outra aba marcou a conversa como lida: a badge desta tem de
             * descer junto, senão fica um número que ninguém consegue
             * baixar porque as mensagens já foram lidas ali do lado. */
            if (dado.tipo === 'lida') { atualizarBadge(dado.total); reconciliarEmBreve(); }
        };
    }

    /* ------------------------------------------- liderança entre abas */

    /* Uma conexão SSE por **navegador**, não por aba.
     *
     * O stream precisa ficar aberto mesmo com a janela fechada — é ele que
     * acende a badge na hora em que alguém escreve, e era esse o pedido.
     * Mas um stream por aba estouraria o orçamento de seis conexões por
     * origem do HTTP/1.1 (o do ambiente local): com quatro abas do sistema
     * abertas, a quinta requisição ficaria esperando sem erro na tela.
     *
     * Então as abas elegem uma líder por um aluguel no `localStorage`, e só
     * ela abre o stream; o que chega é repassado às demais pelo
     * `BroadcastChannel`. Fechar a aba líder libera o aluguel na hora, e a
     * próxima assume na renovação seguinte.
     *
     * `localStorage` não é atômico, então duas abas podem reivindicar no
     * mesmo instante. Em vez de um protocolo de exclusão — caro para o que
     * está em jogo —, quem escreve confere depois se o aluguel continua
     * seu. O pior caso é uma aba a mais com stream aberto por alguns
     * segundos, que é exatamente o estado anterior a esta mudança. */
    function liderAtual() {
        try { return JSON.parse(localStorage.getItem(CHAVE_LIDER) || 'null'); } catch (e) { return null; }
    }

    function disputarLideranca() {
        if (!canal) { conectar(); return; }
        var atual = liderAtual();
        var vago = !atual || (Date.now() - atual.em) > LIDER_VENCE;
        if (vago || atual.id === meuId) {
            guardar(CHAVE_LIDER, JSON.stringify({ id: meuId, em: Date.now() }));
            /* Confere depois de escrever: se outra aba escreveu por cima no
             * mesmo instante, ela é a líder e esta recolhe o stream. */
            window.setTimeout(function () {
                var dono = liderAtual();
                if (dono && dono.id === meuId) { conectar(); } else { desconectar(); }
            }, 120);
            return;
        }
        desconectar();
    }

    function largarLideranca() {
        var atual = liderAtual();
        if (atual && atual.id === meuId) {
            try { localStorage.removeItem(CHAVE_LIDER); } catch (e) { /* modo privado */ }
        }
    }

    /* -------------------------------------------------- abrir e fechar */

    function guardar(chave, valor) {
        try { localStorage.setItem(chave, valor); } catch (e) { /* modo privado */ }
    }

    function lido(chave) {
        try { return localStorage.getItem(chave); } catch (e) { return null; }
    }

    /* `comFoco` so e verdadeiro quando a pessoa clicou no botao. Na
     * abertura automatica — janela que estava aberta na tela anterior —
     * o foco fica onde estava: roubar o cursor a cada navegacao faria
     * quem digita num formulario perder a linha no meio. */
    /* Abrir e fechar a janela não mexe mais no stream: ele é da aba, não da
     * janela, e fica de pé para acender a badge com a janela fechada. Quem
     * decide quem o mantém é `disputarLideranca`. */
    function abrir(comFoco) {
        raiz.hidden = false;
        botao.setAttribute('aria-expanded', 'true');
        guardar(CHAVE_ABERTA, '1');
        aplicarGeometria();
        carregarEstado();
        if (comFoco && filtro) { filtro.focus(); }
    }

    function fechar() {
        raiz.hidden = true;
        botao.setAttribute('aria-expanded', 'false');
        guardar(CHAVE_ABERTA, '');
        botao.focus();
    }

    botao.addEventListener('click', function () {
        if (raiz.hidden) { abrir(true); } else { fechar(); }
    });

    raiz.addEventListener('click', function (evento) {
        var acao = evento.target.closest('[data-nd-tc]');
        if (!acao) { return; }
        if (acao.dataset.ndTc === 'fechar') { fechar(); }
        if (acao.dataset.ndTc === 'lista') {
            janela.classList.remove('is-conversa');
            botaoVoltar(false);
        }
    });

    function botaoVoltar(mostrar) {
        var alvo = raiz.querySelector('[data-nd-tc="lista"]');
        if (alvo) { alvo.hidden = !mostrar; }
    }

    /* Esc fecha, mas só com o foco dentro da janela. Um Esc global roubaria
     * o atalho do modal do Bootstrap, que está por cima. */
    raiz.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') { fechar(); }
    });

    /* ------------------------------------- arrastar e redimensionar */

    function celular() {
        return window.matchMedia('(max-width: 575.98px)').matches;
    }

    function aplicarGeometria() {
        if (celular()) { return; }
        var gravada;
        try { gravada = JSON.parse(lido(CHAVE_GEOMETRIA) || 'null'); } catch (e) { gravada = null; }
        if (!gravada) { return; }
        var largura = Math.max(320, Math.min(gravada.w, window.innerWidth));
        var altura = Math.max(300, Math.min(gravada.h, window.innerHeight));
        janela.style.width = largura + 'px';
        janela.style.height = altura + 'px';
        posicionar(gravada.x, gravada.y, largura, altura);
    }

    function posicionar(x, y, largura, altura) {
        /* Sempre com uma faixa visível: uma janela gravada num monitor
         * largo e reaberta num notebook ficaria inteiramente fora da tela,
         * e não haveria como trazê-la de volta. */
        var maxX = window.innerWidth - MARGEM_VISIVEL;
        var maxY = window.innerHeight - MARGEM_VISIVEL;
        janela.style.left = Math.max(-(largura - MARGEM_VISIVEL), Math.min(x, maxX)) + 'px';
        janela.style.top = Math.max(0, Math.min(y, maxY)) + 'px';
        janela.style.right = 'auto';
        janela.style.bottom = 'auto';
    }

    function gravarGeometria() {
        var caixa = janela.getBoundingClientRect();
        guardar(CHAVE_GEOMETRIA, JSON.stringify({
            x: Math.round(caixa.left), y: Math.round(caixa.top),
            w: Math.round(caixa.width), h: Math.round(caixa.height),
        }));
    }

    function arrastavel(gatilho, aoMover) {
        gatilho.addEventListener('pointerdown', function (evento) {
            if (celular() || evento.button !== 0) { return; }
            /* Clique num botão da barra não arrasta a janela. */
            if (evento.target.closest('[data-nd-tc]')) { return; }
            var caixa = janela.getBoundingClientRect();
            var inicio = { x: evento.clientX, y: evento.clientY, caixa: caixa };
            /* `setPointerCapture` é o que faz o arrasto continuar quando o
             * ponteiro sai da janela — sem ele, mover rápido solta a
             * janela no meio do caminho. */
            gatilho.setPointerCapture(evento.pointerId);
            janela.classList.add('is-dragging');
            evento.preventDefault();

            function mover(e) { aoMover(e, inicio); }
            function soltar(e) {
                gatilho.releasePointerCapture(e.pointerId);
                gatilho.removeEventListener('pointermove', mover);
                gatilho.removeEventListener('pointerup', soltar);
                gatilho.removeEventListener('pointercancel', soltar);
                janela.classList.remove('is-dragging');
                gravarGeometria();
            }
            gatilho.addEventListener('pointermove', mover);
            gatilho.addEventListener('pointerup', soltar);
            gatilho.addEventListener('pointercancel', soltar);
        });
    }

    if (barra) {
        arrastavel(barra, function (evento, inicio) {
            posicionar(
                inicio.caixa.left + (evento.clientX - inicio.x),
                inicio.caixa.top + (evento.clientY - inicio.y),
                inicio.caixa.width, inicio.caixa.height
            );
        });
    }

    if (alca) {
        arrastavel(alca, function (evento, inicio) {
            janela.style.width = Math.max(320, inicio.caixa.width + (evento.clientX - inicio.x)) + 'px';
            janela.style.height = Math.max(300, inicio.caixa.height + (evento.clientY - inicio.y)) + 'px';
        });
    }

    window.addEventListener('resize', function () {
        if (raiz.hidden) { return; }
        aplicarGeometria();
        /* Girar o aparelho ou arrastar a janela do navegador entre telas
         * cruza a faixa de celular: o botao "voltar" precisa aparecer e
         * sumir junto, senao fica um controle morto na barra. */
        botaoVoltar(celular() && !!pessoaAtual);
    });

    /* --------------------------------------------------------- partida */

    ajustarAltura();
    atualizarBadge(totalNaoLidas);
    if (lido(CHAVE_ABERTA)) { abrir(false); }

    /* O stream sobe com a página, e não com a janela: é ele que acende a
     * badge no instante em que alguém escreve, com a janela fechada e a
     * aba atrás de outra. A sondagem continua, mais espaçada, como rede de
     * segurança — reconcilia contadores depois de uma queda e mantém a
     * presença viva nas abas que não são a líder. */
    disputarLideranca();
    relogioLider = window.setInterval(disputarLideranca, LIDER_RENOVA);
    carregarEstado();
    relogio = window.setInterval(carregarEstado, POLL_SEGUNDOS * 1000);

    window.addEventListener('pagehide', function () {
        window.clearInterval(relogio);
        window.clearInterval(relogioLider);
        /* Largar o aluguel é o que faz a próxima aba assumir em três
         * segundos em vez de esperar o vencimento. */
        largarLideranca();
        desconectar();
    });

    /* Voltar pelo botão "voltar" do navegador pode restaurar a página do
     * cache de retrocesso (bfcache) em vez de recarregá-la. O `pagehide`
     * acima já tinha desligado os temporizadores e o stream, e nada os
     * religava: a aba voltava viva na tela e morta por dentro — sem badge,
     * sem mensagem chegando, e sem nenhum sinal de que parou. Religar é a
     * única coisa a fazer aqui. */
    window.addEventListener('pageshow', function (evento) {
        if (!evento.persisted) { return; }
        disputarLideranca();
        relogioLider = window.setInterval(disputarLideranca, LIDER_RENOVA);
        carregarEstado();
        relogio = window.setInterval(carregarEstado, POLL_SEGUNDOS * 1000);
    });
})();
