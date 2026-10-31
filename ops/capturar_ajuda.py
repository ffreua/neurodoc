"""Tira as capturas do manual, sempre do mesmo jeito.

As imagens de `static/help/` sao telas reais do produto. Ate a 1.30 parte delas
saiam de uma sessao de navegador conduzida a mao -- e o documento de
homologacao registra que o Chrome foi morto tres vezes por falta de
memoria no meio do trabalho. Uma sequencia longa de capturas numa maquina
que ja tem navegador aberto e exatamente o caso que estoura.

Este roteiro resolve o problema mudando de lugar: o navegador roda
**dentro do Docker**, na rede do proprio sistema, e nao disputa memoria
com o navegador de quem esta trabalhando. Roda assim, da raiz do projeto:

    docker run --rm --network neurodoc_local \\
      -v "<raiz>/ops:/ops:ro" -v "<raiz>/static/help:/saida" \\
      mcr.microsoft.com/playwright/python:v1.47.0-jammy \\
      python /ops/capturar_ajuda.py

E `scripts/capturar_ajuda.sh` faz exatamente isso, sem a linha de comando.

**Por que um roteiro e nao um passo a passo escrito.** Manual apodrece
quando a tela muda e a imagem fica. Com a captura automatizada, atualizar
o manual inteiro e um comando -- e o que era um dia de trabalho manual
deixa de ser motivo para adiar.

**Nenhum dado real aparece.** Tudo sai do banco de demonstracao, com
pacientes sinteticos. O manual e publico, e isso e condicao, nao detalhe.
"""

import hashlib
import hmac
import json
import os
import struct
import sys
import time

BASE = os.environ.get('NEURODOC_URL', 'http://app:8000')
SAIDA = os.environ.get('NEURODOC_SAIDA', '/saida')

#: Quem entra para tirar cada captura. O dono-e-medico da demonstracao ve
#: tudo; a secretaria existe aqui para a tela que so ela abre no fluxo
#: normal, e para provar que a captura nao veio de um acesso privilegiado
#: que o artigo nao descreve.
DONO = ('doctor-a@demo.neurodoc.local', 'DemoS3nha!123')

#: A clinica de onde sai cada captura. Ver `entrar()`.
CLINICA = 'Clinica Demo A'

#: `(arquivo, caminho, preparo)`. `preparo` e o nome de uma funcao deste
#: modulo, ou `None` -- algumas telas nascem vazias no banco de
#: demonstracao e a captura de uma tela vazia nao ensina nada.
TELAS = [
    # As 21 que ate a 1.30 eram tiradas a mao, e as dos quatro artigos novos.
    # `{nome}` vem dos ids que `ops/preparar_ajuda.py` imprime.
    ('paciente-lista.png', '/app/patients/', None),
    ('paciente-cadastro.png', '/app/patients/new/', None),
    ('paciente-foto.png', '/app/patients/new/', 'foco_foto'),
    ('paciente-ficha.png', '/app/patients/{carlos}/', None),
    ('agenda-semana.png', '/app/scheduling/?date={segunda}', None),
    ('agenda-marcar.png', '/app/scheduling/?date={segunda}', 'abre_marcar'),
    ('atendimento-abas.png', '/app/clinical/{atendimento}/', None),
    ('exame-roteiro.png', '/app/clinical/{atendimento}/', 'aba_exame'),
    ('exame-escalas.png', '/app/clinical/{atendimento}/', 'foco_escalas'),
    ('documento-novo.png', '/app/documents/encounters/{atendimento}/medical/new/', None),
    ('documento-assinatura.png', '/app/documents/signing/credentials/', None),
    ('documento-verificar.png', '/verificar/{token}/', None),
    ('entrega-documento.png', '/app/documents/medical/{documento}/', 'foco_entrega'),
    ('solicitacoes-portal.png', '/solicitacoes/{slug}/', None),
    ('solicitacoes-fila.png', '/app/documents/solicitacoes/', None),
    ('codigos-cid.png', '/app/codigos/', 'busca_cid'),
    ('codigos-tuss.png', '/app/codigos/?aba=tuss', 'busca_tuss'),
    ('chat-nova.png', '/app/ai/chat/', 'abre_nova_conversa'),
    ('chat-conversa.png', '/app/ai/chat/{chat}/', None),
    ('sncr-painel.png', '/app/sncr/', None),
    ('sncr-conduta.png', '/app/clinical/{atendimento}/', 'foco_sncr_conduta'),
    ('sncr-receita.png', '/app/documents/encounters/{atendimento}/medical/new/?receita=sncr_rce', 'foco_medicamento'),
    ('modelos-lista.png', '/app/modelos/', None),
    ('modelos-conduta.png', '/app/clinical/{atendimento}/', 'foco_modelos_conduta'),
    ('modelos-emitir.png', '/app/modelos/atendimento/{atendimento}/?modelo=s:queixa-cognitiva', None),
    ('tiss-inicio.png', '/app/tiss/', None),
    ('tiss-guia.png', '/app/tiss/guias/{guia_rascunho}/', None),
    ('tiss-plano.png', '/app/tiss/faturar/', 'monta_plano'),
    ('exames-agenda.png', '/app/exames/?recurso={psg}&dia={noite}', None),
    ('exames-reserva.png', '/app/exames/reservas/{reserva_enmg}/', None),
    ('indicadores-painel.png', '/app/reporting/', None),
    ('indicadores-plano.png', '/app/reporting/', 'foco_plano'),
    ('financeiro-recebiveis.png', '/app/finance/', None),
    ('financeiro-pagamento.png', '/app/finance/', 'abre_pagamento'),
    ('disponibilidade-grade.png', '/app/scheduling/configurar/', None),
    ('disponibilidade-duracao.png', '/app/scheduling/configurar/', 'foco_duracao'),
    ('disponibilidade-bloqueio.png', '/app/scheduling/configurar/', 'foco_bloqueio'),
    ('clinica-identidade.png', '/app/org/clinica/', None),
    ('clinica-logotipo.png', '/app/org/clinica/', 'foco_logotipo'),
    ('clinica-encarregado.png', '/app/org/clinica/', 'foco_encarregado'),
    ('convenios-lista.png', '/app/org/convenios/', None),
    ('convenios-valores.png', '/app/org/valores/', None),
    ('equipe-lista.png', '/app/org/equipe/', None),
    ('equipe-registro.png', '/app/org/equipe/', 'abre_registro_profissional'),
    ('mensageria-config.png', '/app/org/mensageria/', None),
    ('mensageria-entregas.png', '/app/org/mensageria/entregas/', None),
    ('campanhas-nova.png', '/app/org/campanhas/nova/', None),
    ('campanhas-andamento.png', '/app/org/campanhas/', None),
    ('notificacoes-sino.png', '/app/reporting/', 'abre_sino'),
    ('notificacoes-lista.png', '/app/notifications/', None),
    ('equipe-chat-janela.png', '/app/reporting/', 'abre_conversa'),
    ('equipe-chat-lista.png', '/app/reporting/', 'abre_chat'),
    ('exportar-tela.png', '/app/reporting/acervo/', None),
    ('exportar-pronta.png', '/app/reporting/acervo/', 'exporta_e_espera'),
    ('suporte-mensagem.png', '/app/mensagem/support/', None),
]

LARGURA, ALTURA = 1280, 860

#: Os ids que `ops/preparar_ajuda.py` imprimiu (linha `IDS {...}`). Sem
#: eles, as telas de um objeto especifico -- a guia, o exame, o documento --
#: nao tem endereco.
IDS = json.loads(os.environ.get('NEURODOC_IDS') or '{}')


def totp(chave_hex):
    """O codigo de seis digitos do autenticador, para a reconfirmacao.

    A area TISS pede o segundo fator de novo, como manda o requisito da ANS,
    e a captura precisa responder sozinha. A chave e a da demonstracao local,
    nunca de conta real; RFC 6238 com SHA-1 e passo de 30 s, o mesmo do
    `django_otp`.
    """
    contador = struct.pack('>Q', int(time.time()) // 30)
    resumo = hmac.new(bytes.fromhex(chave_hex), contador, 'sha1').digest()
    deslocamento = resumo[-1] & 0x0F
    numero = struct.unpack('>I', resumo[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return f'{numero % 1000000:06d}'


def responder_mfa(page):
    """Se a tela pediu o segundo fator, responde e volta para onde ia."""
    if '/accounts/mfa' not in page.url:
        return
    if not IDS.get('totp'):
        raise RuntimeError('a tela pediu o segundo fator e NEURODOC_IDS nao trouxe a chave TOTP')
    campo = page.locator('input[name="token"], input[name="code"], input[name="otp_token"]').first
    campo.fill(totp(IDS['totp']))
    page.locator('button[type="submit"]').first.click()
    assentar(page)


# ------------------------------------------------------------- preparos
#
# Cada um deixa a tela no estado que o artigo descreve. Sem eles, metade
# das capturas mostraria um painel vazio -- e captura de tela vazia ensina
# menos que paragrafo nenhum.

def foco_plano(page):
    """O painel inteiro cabe na tela, entao rolar nao muda nada.

    A captura do painel e a do consumo do plano sairiam byte a byte
    identicas -- e foi o que aconteceu. Aqui se captura **o cartao**, que
    e o que a legenda promete.
    """
    return _cartao(page, 'Pacientes do plano')


def foco_duracao(page):
    _centrar(page, _cartao(page, 'Duração por tipo'))


def foco_bloqueio(page):
    _centrar(page, _cartao(page, 'Bloqueios, férias'))


def foco_logotipo(page):
    _centrar(page, _cartao(page, 'Logotipo'))


def foco_encarregado(page):
    _centrar(page, page.locator('#id_dpo_name'))


def abre_registro_profissional(page):
    """Abre o formulário que vive no modal da equipe.

    A URL `registro-profissional/` recebe somente POST. Navegar até ela foi o
    que gerou a captura HTTP 405 publicada anteriormente; a tela real é este
    modal, aberto pelo botão Registro.
    """
    botao = page.locator('button[data-bs-target^="#crm-"]').first
    botao.wait_for(state='visible', timeout=5000)
    alvo = botao.get_attribute('data-bs-target')
    botao.click()
    modal = page.locator(alvo)
    modal.wait_for(state='visible', timeout=5000)
    return modal.locator('.modal-content')


def abre_pagamento(page):
    """Entra no recebivel, que e onde a baixa acontece.

    A baixa nao mora na lista: `finance/urls.py` poe
    `<uuid>/payments/` sob o recebivel. Uma captura da lista com legenda
    "registro de pagamento" mostraria a tela errada.
    """
    page.locator('table a.fw-semibold').first.click()
    assentar(page)
    _centrar(page, page.locator('#pay-amount'))


def abre_sino(page):
    sino = page.locator('[aria-label="Notificações"], .nxl-h-item a[href*="notifications"]').first
    if sino.count():
        sino.click()
        page.wait_for_timeout(700)


def abre_chat(page):
    """Abre a janela flutuante e para na lista de pessoas."""
    # O clique so abre depois que o JavaScript da janela ligou o
    # ouvinte; um unico clique logo apos o `DOMContentLoaded` cai no
    # vazio de vez em quando. Insistir e mais barato que adivinhar uma
    # espera fixa longa o bastante para a maquina mais lenta.
    for _ in range(10):
        page.locator('#nd-tc-toggle').click()
        try:
            page.locator('#nd-tc-pessoas li').first.wait_for(state='visible', timeout=2000)
            return
        except Exception:                                   # noqa: BLE001
            page.wait_for_timeout(500)
    raise RuntimeError('a janela de mensagens nao abriu')


def abre_conversa(page):
    """A mesma janela, com uma conversa aberta."""
    abre_chat(page)
    page.locator('#nd-tc-pessoas li').first.click()
    page.locator('#nd-tc-vazio').wait_for(state='hidden', timeout=5000)
    page.wait_for_timeout(600)


def exporta_e_espera(page):
    """Pede uma exportacao e volta para a tela que lista as prontas.

    O POST redireciona para o **detalhe** da exportacao
    (`reporting/views.py` termina em `redirect('reporting:export-detail')`),
    e nao para o acervo. Recarregar dali nunca faria "Ultimas exportacoes"
    aparecer, porque essa tela nao tem esse cartao.
    """
    page.locator('form:has(input[value="acervo_pacientes"]) button[value="md"]').click()
    assentar(page)
    for _ in range(20):
        page.goto(BASE + '/app/reporting/acervo/', wait_until='domcontentloaded')
        assentar(page, 400)
        if page.locator('.list-group-item a[href*="/exports/"]').count():
            break
        page.wait_for_timeout(1500)
    else:
        raise RuntimeError('a exportacao nao ficou pronta; o worker esta de pe?')
    return _cartao(page, 'Últimas exportações')


def foco_foto(page):
    return _cartao(page, 'Fotografia do paciente')


def abre_marcar(page):
    """Clica no primeiro horario livre da semana: o modal de marcar."""
    page.locator('.nd-slot-free').first.click()
    page.locator('.modal.show').first.wait_for(state='visible', timeout=5000)
    page.wait_for_timeout(500)


def _aba(page, alvo):
    page.locator(f'button[data-bs-target="#{alvo}"]').first.click()
    page.locator(f'#{alvo}').wait_for(state='visible', timeout=5000)
    page.wait_for_timeout(400)


def aba_exame(page):
    _aba(page, 'tab-exame')


def foco_escalas(page):
    """Com a escala de Glasgow aberta: o cartao vazio nao mostra o que o
    artigo descreve (pontuacao automatica e faixa)."""
    _aba(page, 'tab-exame')
    seletor = page.locator('#scale-picker')
    opcoes = [o for o in seletor.locator('option').all() if 'Glasgow' in (o.inner_text() or '')]
    if opcoes:
        seletor.select_option(value=opcoes[0].get_attribute('value'))
        page.wait_for_timeout(800)
    _centrar(page, seletor)


def foco_entrega(page):
    return _cartao(page, 'Entrega ao paciente')


def busca_cid(page):
    page.fill('#nd-cid-q', 'epilepsia')
    page.wait_for_timeout(1500)


def busca_tuss(page):
    page.fill('#nd-tuss-q', 'ressonancia cranio')
    page.wait_for_timeout(1500)


def abre_nova_conversa(page):
    page.locator('button, a').filter(has_text='Nova conversa').first.click()
    page.locator('.modal.show').first.wait_for(state='visible', timeout=5000)
    page.wait_for_timeout(500)


def foco_sncr_conduta(page):
    """So o campo da conduta e os botoes: o bloco dos modelos, logo abaixo,
    e a captura do outro artigo -- centrar os dois dava a mesma imagem."""
    _aba(page, 'tab-conduta')
    painel = page.locator('#tab-conduta')
    _centrar(page, painel.locator('text=Receita controlada (SNCR)').first)
    caixa = painel.bounding_box()
    botao = painel.locator('text=Receita controlada (SNCR)').first.bounding_box()
    return {'clip': {'x': caixa['x'], 'y': caixa['y'], 'width': caixa['width'],
                     'height': botao['y'] + botao['height'] + 24 - caixa['y']}}


def foco_modelos_conduta(page):
    _aba(page, 'tab-conduta')
    bloco = page.locator('#nd-modelos')
    _centrar(page, bloco)
    return bloco


def foco_medicamento(page):
    """A receita do SNCR ja com o saldo de numeros e o primeiro medicamento."""
    campo = page.locator('input[name="item1_nome"]')
    _centrar(page, campo)


def monta_plano(page):
    """Marca as guias da fila e pede o plano dos lotes — a tela que mostra
    quantos lotes vao sair antes de qualquer arquivo existir."""
    for caixa in page.locator('input[name="guia"]').all():
        caixa.check()
    page.locator('button[type="submit"]').filter(has_text='Montar lote com as marcadas').click()
    assentar(page)


def _fechar_chat(page):
    """Fecha a janela de mensagens antes de cada captura.

    Ela nao e da pagina: vive no shell e **atravessa a navegacao**, com o
    estado de aberta guardado no navegador. Depois das duas capturas do
    chat, ela continuou aberta e apareceu por cima da captura seguinte --
    a exportacao saiu com metade da janela do chat colada em cima. A
    comparacao byte a byte nao pega isso, porque as imagens sao mesmo
    diferentes entre si.
    """
    painel = page.locator('#nd-teamchat')
    if painel.count() and painel.get_attribute('hidden') is None:
        page.locator('[data-nd-tc="fechar"]').click()
        page.wait_for_timeout(300)


def _cartao(page, texto):
    """O cartao que contem aquele texto.

    Ancorar no texto do titulo e nao numa classe porque as classes vem do
    tema e se repetem em toda a tela; o titulo e o que distingue um
    cartao do vizinho.
    """
    return page.locator('.card').filter(has_text=texto).first


def _centrar(page, alvo):
    """Rola ate deixar o alvo no meio da tela.

    `scroll_into_view_if_needed` nao serve: ele nao faz nada quando o
    elemento ja esta visivel de raspao no rodape, e a captura sai igual a
    da tela sem preparo -- foi assim que seis capturas sairam repetidas
    na primeira rodada, sem nenhum erro aparecer.
    """
    alvo.wait_for(state='visible', timeout=5000)
    alvo.evaluate("e => e.scrollIntoView({block: 'center'})")
    page.wait_for_timeout(400)


# ----------------------------------------------------------------- fluxo

def assentar(page, ms=900):
    """Espera a tela parar de mexer.

    Nao se usa `networkidle` aqui: as telas de `/app/` mantem conexoes SSE
    abertas o tempo todo -- chat da equipe e notificacoes ao vivo --, e a
    rede nunca fica ociosa. Playwright esperaria trinta segundos e
    desistiria em toda captura.
    """
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_timeout(ms)


def entrar(page, email, senha):
    """Entra e escolhe a clinica **pelo nome**.

    Escolher "a primeira do seletor" foi o erro mais caro desta captura:
    o dono da demonstracao tem vinculo em duas clinicas, e a primeira da
    lista e a Clinica Demo B -- a vazia, que existe para exercitar a
    troca de organizacao. O manual inteiro saiu dela na primeira rodada,
    com agenda sem horario e financeiro sem recebivel, e nada acusou o
    problema porque todas as telas responderam 200.
    """
    page.goto(f'{BASE}/accounts/login/', wait_until='domcontentloaded')
    assentar(page, 500)
    _gravar(page, 'entrar-login.png')
    page.fill('input[name="username"], input[name="email"]', email)
    page.fill('input[name="password"]', senha)
    page.click('button[type="submit"]')
    assentar(page)
    responder_mfa(page)
    escolha = page.locator('form button[type="submit"]').filter(has_text=CLINICA)
    if escolha.count():
        _gravar(page, 'entrar-organizacao.png')
        escolha.first.click()
        assentar(page)
    # Conferir depois de entrar: o nome da clinica fica no cabecalho, e um
    # seletor que nao apareceu nao prova que se caiu na clinica certa.
    if CLINICA not in page.content():
        raise RuntimeError(f'entrei, mas nao em "{CLINICA}" -- {page.url}: '
                           + page.locator('body').inner_text()[:400].replace(chr(10), ' / '))


FEITAS = {}


def _gravar(page, arquivo, alvo=None):
    destino = os.path.join(SAIDA, arquivo)
    if isinstance(alvo, dict):              # um recorte da pagina
        page.screenshot(path=destino, **alvo)
    else:
        (alvo if alvo is not None else page).screenshot(path=destino)
    with open(destino, 'rb') as fh:
        FEITAS[arquivo] = hashlib.sha256(fh.read()).hexdigest()
    print(f'  {arquivo}')


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SAIDA, exist_ok=True)
    feitas, falhas = FEITAS, []
    with sync_playwright() as p:
        # pt-BR no proprio navegador, e nao so no contexto: o campo de data segue
        # o idioma do processo, e sem isto saia "mm/dd/yyyy" nas capturas -- o
        # que nenhum usuario no Brasil ve.
        navegador = p.chromium.launch(args=['--no-sandbox', '--lang=pt-BR'], env={**os.environ, 'LANG': 'pt_BR.UTF-8'})
        contexto = navegador.new_context(
            viewport={'width': LARGURA, 'height': ALTURA},
            device_scale_factor=2,        # nitidez em tela de alta densidade
            locale='pt-BR',
        )
        page = contexto.new_page()
        entrar(page, *DONO)
        if '/accounts/login' in page.url:
            print('FALHA: nao consegui entrar; confira o banco de demonstracao')
            return 1

        for arquivo, caminho, preparo in TELAS:
            try:
                caminho = caminho.format(**IDS)
            except KeyError as exc:
                falhas.append(f'{arquivo}: falta o id {exc} (rodou ops/preparar_ajuda.py?)')
                continue
            resposta = page.goto(BASE + caminho, wait_until='domcontentloaded')
            assentar(page, 700)
            if '/accounts/mfa' in page.url:
                responder_mfa(page)
                resposta = page.goto(BASE + caminho, wait_until='domcontentloaded')
                assentar(page, 700)
            _fechar_chat(page)
            if resposta is None or not resposta.ok:
                status = resposta.status if resposta is not None else 'sem resposta'
                falhas.append(f'{arquivo}: {caminho} respondeu {status}')
                continue
            if page.url.rstrip('/').endswith('/accounts/login'):
                falhas.append(f'{arquivo}: a tela exigiu login de novo')
                continue
            texto = page.locator('body').inner_text().lower()
            if 'page not found' in texto or 'esta página não está funcionando' in texto:
                falhas.append(f'{arquivo}: a captura contém uma página de erro')
                continue
            # Um preparo pode devolver um elemento, e entao e ele que sai
            # na imagem. E o caminho para o que nao se resolve rolando a
            # tela: um cartao no alto de uma pagina curta continua no alto
            # depois de qualquer rolagem, e a captura sairia igual a da
            # tela sem preparo nenhum.
            alvo = None
            if preparo:
                try:
                    alvo = globals()[preparo](page)
                except Exception as exc:                    # noqa: BLE001
                    falhas.append(f'{arquivo}: preparo {preparo} falhou '
                                  f'({exc.__class__.__name__}: {str(exc)[:80]})')
                    continue
            page.wait_for_timeout(400)
            _gravar(page, arquivo, alvo)
        navegador.close()

    # Duas capturas identicas significam preparo que nao surtiu efeito --
    # e esse e o erro que passa despercebido, porque nada estoura: o
    # arquivo e gravado, o roteiro termina em zero e o manual publica a
    # mesma tela com duas legendas diferentes. Na primeira rodada foram
    # seis, e so a comparacao byte a byte denunciou.
    por_hash = {}
    for arquivo, digest in feitas.items():
        por_hash.setdefault(digest, []).append(arquivo)
    for repetidas in por_hash.values():
        if len(repetidas) > 1:
            falhas.append('capturas identicas: ' + ', '.join(sorted(repetidas)))

    print()
    print(f'{len(feitas)} captura(s) em {SAIDA}')
    for falha in falhas:
        print(f'  FALHA: {falha}')
    return 1 if falhas else 0


if __name__ == '__main__':
    sys.exit(main())
