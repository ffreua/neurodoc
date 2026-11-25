"""WhatsApp automático pela conta Twilio **da própria clínica** (BYO).

A clínica contrata a Twilio, cadastra o próprio número pelo *Self Sign-up*,
cria e aprova os modelos de mensagem, e paga a Twilio e a Meta. O sistema
guarda as credenciais dela (cifradas, `WhatsAppTwilio`) e chama a API em
nome dela. Decisões e fontes oficiais em `docs/governance/whatsapp-twilio.md`;
o tutorial das clínicas em `base/ajuda_whatsapp.py`.

Este módulo fala com a Twilio por HTTP, com `httpx` (já dependência do
projeto). O SDK oficial não entrou: traria `aiohttp` e outras dependências
para quatro chamadas REST e uma conferência de assinatura, e a assinatura é
conferida aqui contra o algoritmo documentado e contra os vetores do próprio
SDK (`checks/check_whatsapp_twilio.py`).

**Só o worker chama a Twilio** (CLAUDE.md §2): as funções que fazem rede são
chamadas pelas tarefas e por `services._send`, nunca por uma view.
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets

from django.utils import timezone

logger = logging.getLogger(__name__)

API = 'https://api.twilio.com/2010-04-01'
CONTENT = 'https://content.twilio.com/v1'
MESSAGING = 'https://messaging.twilio.com/v2'
TEMPO_LIMITE = 15

#: As ocasiões em que o WhatsApp pode ser usado, e o **contrato de variáveis**
#: de cada uma: o modelo que a clínica aprova na Meta tem de ter exatamente
#: estas variáveis, nesta ordem. Nada clínico entra — nem médico, nem tipo de
#: consulta, nem nome do paciente (quem recebe pode ser um parente). Ver a
#: seção "O que o canal faz" do documento de governança.
#:
#: O texto sugerido obedece às regras de aprovação da Meta: variável nem no
#: começo nem no fim, nenhuma colada em outra, numeradas em sequência.
EVENTOS = {
    'lembrete': {
        'rotulo': 'Lembrete de consulta',
        'quando': 'Na véspera e duas horas antes do horário (e na véspera do exame '
                  'marcado na agenda de exames).',
        'variaveis': ['nome da clínica', 'data (dd/mm/aaaa)', 'hora (hh:mm)'],
        'sugestao': 'Olá! Este é um lembrete de {{1}}: você tem um horário marcado '
                    'em {{2}} às {{3}}. Se não puder comparecer, avise a clínica pelos '
                    'canais habituais. Esta mensagem é automática e não lê respostas.',
    },
    'marcado': {
        'rotulo': 'Horário marcado',
        'quando': 'Logo depois que a recepção marca o horário.',
        'variaveis': ['nome da clínica', 'data (dd/mm/aaaa)', 'hora (hh:mm)'],
        'sugestao': 'Olá! {{1}} confirma o seu horário em {{2}} às {{3}}. Em caso de '
                    'dúvida, fale com a clínica pelos canais habituais. Esta mensagem '
                    'é automática e não lê respostas.',
    },
    'remarcado': {
        'rotulo': 'Horário remarcado',
        'quando': 'Quando o horário muda de dia ou de hora.',
        'variaveis': ['nome da clínica', 'nova data (dd/mm/aaaa)', 'nova hora (hh:mm)'],
        'sugestao': 'Olá! {{1}} informa que o seu horário foi remarcado para {{2}} às '
                    '{{3}}. Em caso de dúvida, fale com a clínica pelos canais habituais. '
                    'Esta mensagem é automática e não lê respostas.',
    },
    'cancelado': {
        'rotulo': 'Horário cancelado',
        'quando': 'Quando o horário é cancelado.',
        'variaveis': ['nome da clínica', 'data (dd/mm/aaaa)', 'hora (hh:mm)'],
        'sugestao': 'Olá! {{1}} informa que o horário de {{2}} às {{3}} foi cancelado. '
                    'Para marcar outro, fale com a clínica pelos canais habituais. Esta '
                    'mensagem é automática e não lê respostas.',
    },
    'documento': {
        'rotulo': 'Documento disponível',
        'quando': 'Quando um documento é emitido para o paciente (o documento não vai '
                  'pelo WhatsApp: vai o link seguro, que pede os 4 últimos dígitos do CPF).',
        'variaveis': ['nome da clínica', 'link seguro do documento'],
        'sugestao': 'Olá! {{1}} disponibilizou um documento para você. Acesse pelo link '
                    'seguro {{2}} e informe os 4 últimos dígitos do CPF do paciente para '
                    'abrir. Esta mensagem é automática e não lê respostas.',
    },
}

#: Situação da mensagem na Twilio → situação da entrega aqui. `read` conta como
#: entregue (não há "lida" na entrega, e a leitura depende de o paciente
#: deixar a confirmação de leitura ligada). As intermediárias não mudam nada:
#: a entrega já está "aceita" desde o envio.
STATUS_ENTREGUE = {'delivered', 'read'}
STATUS_FALHOU = {'failed', 'undelivered', 'canceled'}

#: Os códigos de erro que a tela explica em português. **Só os confirmados na
#: documentação oficial**; o resto aparece com o código e o link da página de
#: erro da Twilio, que é onde a explicação de verdade está.
ERROS_CONHECIDOS = {
    '63016': 'Fora da janela de 24 horas o WhatsApp só entrega modelo aprovado. '
             'Confira se o modelo desta ocasião está aprovado e se o identificador '
             '(HX…) foi copiado certo.',
}


class WhatsAppIndisponivel(Exception):
    """O canal não está operacional para esta clínica agora."""


class WhatsAppRecusado(Exception):
    """A Twilio recusou o pedido (4xx): repetir não resolve."""

    def __init__(self, codigo, texto):
        super().__init__(texto)
        self.codigo = codigo
        self.texto = texto


class CredencialRecusada(WhatsAppRecusado):
    """Account SID ou Auth Token recusado (401)."""


class FalhaDeTransporte(Exception):
    """Rede, tempo esgotado ou erro do lado da Twilio (5xx): tentar de novo."""


# ------------------------------------------------------------------ estado

def liberado_na_instalacao():
    from base.models import InstallationSettings

    return InstallationSettings.carregar().whatsapp_twilio_liberado


def config_da_clinica(tenant_id, criar=False):
    from .models import WhatsAppTwilio

    if criar:
        config, _ = WhatsAppTwilio.objects.get_or_create(
            tenant_id=tenant_id, defaults={'token_webhook': secrets.token_urlsafe(32)},
        )
        return config
    return WhatsAppTwilio.objects.filter(tenant_id=tenant_id).first()


def modelos_da_clinica(tenant_id):
    """Um `WhatsAppModelo` por ocasião, na ordem de `EVENTOS`."""
    from .models import WhatsAppModelo

    existentes = {m.evento: m for m in WhatsAppModelo.objects.filter(tenant_id=tenant_id)}
    return [
        existentes.get(evento) or WhatsAppModelo(tenant_id=tenant_id, evento=evento)
        for evento in EVENTOS
    ]


def modelo_aprovado(modelo):
    """O modelo serve para enviar: tem SID, foi aprovado e tem as variáveis certas."""
    return bool(
        modelo is not None and modelo.content_sid and modelo.conferido_em
        and modelo.aprovacao == 'approved'
        and modelo.variaveis == len(EVENTOS[modelo.evento]['variaveis'])
    )


ESTADOS = {
    'nao_configurado': ('Não configurado', 'bg-gray-200 text-dark'),
    'pendente': ('Pendente de verificação', 'bg-soft-warning text-warning'),
    'invalido': ('Inválido', 'bg-soft-danger text-danger'),
    'validado': ('Validado', 'bg-soft-info text-info'),
    'operacional': ('Operacional', 'bg-soft-success text-success'),
    'desativado': ('Desativado', 'bg-gray-200 text-dark'),
}


def estado(config, modelos=None, liberado=None):
    """O estado que a tela mostra, derivado — nunca gravado.

    Gravado, ele poderia dizer "operacional" depois de a instalação recolher
    o canal ou de um modelo deixar de estar aprovado. Derivado, é sempre o
    que vale agora. Os seis estados estão na tabela do documento de
    governança.
    """
    if config is None or not config.tem_credenciais:
        return 'nao_configurado'
    if config.erro_codigo and not config.verificado_em:
        return 'invalido'
    if not config.verificado_em:
        return 'pendente'
    if not config.ativo:
        return 'desativado'
    if liberado is None:
        liberado = liberado_na_instalacao()
    if modelos is None:
        modelos = modelos_da_clinica(config.tenant_id)
    if liberado and any(m.ligado and modelo_aprovado(m) for m in modelos):
        return 'operacional'
    return 'validado'


def para_enviar(tenant_id, evento):
    """`(config, modelo)` se esta ocasião sai por WhatsApp nesta clínica, ou `None`.

    É a pergunta que a escolha de canal faz (`services._channels_for`) e que o
    envio refaz (`services._send`): entre uma e outra a instalação pode ter
    recolhido o canal, a clínica suspendido, ou o modelo deixado de valer.
    """
    if evento not in EVENTOS:
        return None
    from .models import WhatsAppModelo

    config = config_da_clinica(tenant_id)
    if config is None or not config.tem_credenciais or not config.verificado_em:
        return None
    if not config.ativo or not liberado_na_instalacao():
        return None
    modelo = WhatsAppModelo.objects.filter(tenant_id=tenant_id, evento=evento, ligado=True).first()
    if not modelo_aprovado(modelo):
        return None
    return config, modelo


def numero_e164(telefone):
    """`+5511987654321`, ou `None` se o telefone não fecha num número válido."""
    from .whatsapp import normalizar_telefone

    digitos = normalizar_telefone(telefone)
    return f'+{digitos}' if digitos else None


def url_do_status(config):
    """A URL do aviso de status, sempre de `PUBLIC_BASE_URL`.

    A assinatura da Twilio é calculada sobre a URL **exata** que ela chamou;
    montar a mesma URL dos dois lados (no envio e na conferência) a partir da
    mesma fonte é o que faz a conta fechar — e o `Host:` da requisição, que é
    do cliente, nunca entra nela.
    """
    from base.seo import absoluta

    return absoluta(f'/whatsapp/status/{config.token_webhook}/')


# -------------------------------------------------------------- assinatura

def assinatura_esperada(auth_token, url, parametros):
    """HMAC-SHA1 da URL seguida dos parâmetros em ordem, em Base64.

    O algoritmo de <https://www.twilio.com/docs/usage/security>: a URL
    completa, depois cada parâmetro do POST em ordem alfabética do nome, nome
    e valor colados, sem separador. Nome repetido entra com cada valor, em
    ordem (como no SDK oficial).
    """
    conteudo = url
    for nome in sorted(set(parametros.keys())):
        valores = parametros.getlist(nome) if hasattr(parametros, 'getlist') else [parametros[nome]]
        for valor in sorted(set(valores)):
            conteudo += nome + valor
    digest = hmac.new(auth_token.encode('utf-8'), conteudo.encode('utf-8'), hashlib.sha1).digest()
    return base64.b64encode(digest).decode('ascii')


def _variantes_de_porta(url):
    """A URL com e sem a porta padrão: a Twilio a mantém num caso e não no outro.

    A documentação avisa que a porta entra na assinatura de SMS e sai na de
    voz sobre HTTPS; o SDK oficial confere as duas formas pelo mesmo motivo.
    """
    from urllib.parse import urlsplit, urlunsplit

    partes = urlsplit(url)
    padrao = {'https': 443, 'http': 80}.get(partes.scheme)
    if partes.port is None and padrao:
        com = partes._replace(netloc=f'{partes.hostname}:{padrao}')
        return [url, urlunsplit(com)]
    if partes.port == padrao:
        sem = partes._replace(netloc=partes.hostname)
        return [url, urlunsplit(sem)]
    return [url]


def assinatura_valida(auth_token, url, parametros, assinatura):
    if not auth_token or not assinatura:
        return False
    return any(
        hmac.compare_digest(assinatura_esperada(auth_token, variante, parametros), assinatura)
        for variante in _variantes_de_porta(url)
    )


# ------------------------------------------------------------------ erros

def traduzir_erro(status_http, corpo):
    """`(codigo, texto)` em português, com o código da Twilio preservado.

    O texto nunca leva a resposta inteira da Twilio (ela pode repetir o
    número do destinatário); leva o código, a explicação quando a temos, e o
    endereço da página de erro oficial.
    """
    codigo = ''
    if isinstance(corpo, dict):
        codigo = str(corpo.get('code') or corpo.get('error_code') or '')
    if status_http == 401:
        return codigo or '401', (
            'A Twilio recusou o Account SID ou o Auth Token. Copie os dois de novo da '
            'página inicial do Console da Twilio (Account Info) e salve.'
        )
    if codigo in ERROS_CONHECIDOS:
        return codigo, f'{ERROS_CONHECIDOS[codigo]} (código {codigo})'
    if codigo:
        return codigo, (
            f'A Twilio recusou o pedido com o código {codigo}. A explicação está em '
            f'https://www.twilio.com/docs/api/errors/{codigo}'
        )
    if status_http == 404:
        return '404', 'A Twilio não encontrou o que foi pedido (identificador errado?).'
    return str(status_http or ''), f'A Twilio respondeu com erro (HTTP {status_http}).'


# --------------------------------------------------------------- cliente

def _pedir(config, metodo, url, dados=None, parametros=None):
    """Uma chamada à API com as credenciais da clínica; devolve o JSON."""
    import httpx

    from base.crypto import SecretUnavailable

    try:
        token = config.auth_token()
    except SecretUnavailable as exc:
        raise WhatsAppIndisponivel('O Auth Token guardado não pôde ser lido.') from exc
    try:
        resposta = httpx.request(
            metodo, url, data=dados, params=parametros,
            auth=(config.account_sid, token), timeout=TEMPO_LIMITE,
        )
    except httpx.HTTPError as exc:
        raise FalhaDeTransporte(exc.__class__.__name__) from exc
    try:
        corpo = resposta.json()
    except ValueError:
        corpo = {}
    if resposta.status_code >= 500:
        raise FalhaDeTransporte(f'HTTP {resposta.status_code}')
    if resposta.status_code >= 400:
        codigo, texto = traduzir_erro(resposta.status_code, corpo)
        classe = CredencialRecusada if resposta.status_code == 401 else WhatsAppRecusado
        raise classe(codigo, texto)
    return corpo


def enviar_modelo(config, modelo, para_e164, variaveis, status_callback=True):
    """Envia o modelo aprovado e devolve o SID da mensagem (`SM…`/`MM…`)."""
    dados = {
        'To': f'whatsapp:{para_e164}',
        'ContentSid': modelo.content_sid,
        'ContentVariables': json.dumps(
            {str(i): str(v) for i, v in enumerate(variaveis, start=1)}, ensure_ascii=False,
        ),
    }
    if config.messaging_service_sid:
        dados['MessagingServiceSid'] = config.messaging_service_sid
    else:
        dados['From'] = f'whatsapp:{config.numero}'
    if status_callback:
        dados['StatusCallback'] = url_do_status(config)
    corpo = _pedir(config, 'POST', f'{API}/Accounts/{config.account_sid}/Messages.json', dados=dados)
    return str(corpo.get('sid') or '')


def consultar_mensagem(config, sid):
    """`(status, codigo_de_erro)` da mensagem na Twilio."""
    corpo = _pedir(config, 'GET', f'{API}/Accounts/{config.account_sid}/Messages/{sid}.json')
    return str(corpo.get('status') or '').lower(), str(corpo.get('error_code') or '')


# ------------------------------------------------------------- verificação

def verificar(config):
    """Confere conta, número e modelos na Twilio, e grava o resultado.

    Só o sucesso grava `verificado_em`. Cada passo que falha para a
    verificação com o motivo em português e o código da Twilio.
    """
    from .models import WhatsAppModelo

    agora = timezone.now()
    config.invalidar_verificacao()
    config.verificacao_concluida_em = agora
    campos = [
        'verificado_em', 'verificacao_concluida_em', 'remetente_status', 'remetente_qualidade',
        'remetente_limite', 'conta_tipo', 'erro_codigo', 'erro_texto', 'updated_at',
    ]
    try:
        conta = _pedir(config, 'GET', f'{API}/Accounts/{config.account_sid}.json')
        situacao = str(conta.get('status') or '').lower()
        config.conta_tipo = str(conta.get('type') or '')[:20]
        if situacao != 'active':
            raise WhatsAppRecusado(
                'conta', f'A conta Twilio está "{situacao or "desconhecida"}", e não ativa. '
                         'Resolva no Console da Twilio (Billing) e verifique de novo.',
            )
        remetentes = _pedir(
            config, 'GET', f'{MESSAGING}/Channels/Senders',
            parametros={'Channel': 'whatsapp', 'PageSize': 50},
        )
        alvo = f'whatsapp:{config.numero}'
        remetente = next(
            (s for s in (remetentes.get('senders') or []) if s.get('sender_id') == alvo), None,
        )
        if remetente is None:
            raise WhatsAppRecusado(
                'numero', f'O número {config.numero} não aparece entre os remetentes de '
                          'WhatsApp desta conta Twilio. Confira o número (com +55 e DDD) ou '
                          'conclua o cadastro em WhatsApp Senders no Console.',
            )
        propriedades = remetente.get('properties') or {}
        config.remetente_status = str(remetente.get('status') or '').upper()[:40]
        config.remetente_qualidade = str(propriedades.get('quality_rating') or '')[:40]
        config.remetente_limite = str(propriedades.get('messaging_limit') or '')[:60]
        if config.remetente_status != 'ONLINE':
            raise WhatsAppRecusado(
                'remetente', f'O número está "{config.remetente_status}" na Twilio, e só '
                             'envia quando estiver ONLINE. O cadastro na Meta pode ainda '
                             'estar em análise.',
            )
    except WhatsAppRecusado as exc:
        config.erro_codigo = str(exc.codigo)[:20]
        config.erro_texto = exc.texto[:300]
        config.save(update_fields=campos)
        return False
    config.verificado_em = agora
    config.save(update_fields=campos)

    for modelo in WhatsAppModelo.objects.filter(tenant_id=config.tenant_id).exclude(content_sid=''):
        conferir_modelo(config, modelo)
    return True


def conferir_modelo(config, modelo):
    """Confere na Twilio se o modelo existe, está aprovado e tem as variáveis certas."""
    esperadas = len(EVENTOS[modelo.evento]['variaveis'])
    modelo.conferido_em = None
    modelo.aprovacao = ''
    modelo.variaveis = None
    modelo.erro_texto = ''
    try:
        conteudo = _pedir(config, 'GET', f'{CONTENT}/Content/{modelo.content_sid}')
        aprovacoes = _pedir(config, 'GET', f'{CONTENT}/Content/{modelo.content_sid}/ApprovalRequests')
    except WhatsAppRecusado as exc:
        modelo.erro_texto = exc.texto[:300]
    else:
        whatsapp = aprovacoes.get('whatsapp') or {}
        modelo.aprovacao = str(whatsapp.get('status') or 'não enviado').lower()[:30]
        modelo.variaveis = len(conteudo.get('variables') or {})
        modelo.idioma = str(conteudo.get('language') or '')[:10]
        modelo.nome_na_twilio = str(conteudo.get('friendly_name') or '')[:200]
        modelo.conferido_em = timezone.now()
        if modelo.aprovacao != 'approved':
            motivo = whatsapp.get('rejection_reason') or ''
            modelo.erro_texto = (
                f'O modelo está "{modelo.aprovacao}" no WhatsApp, e só é usado quando '
                f'aprovado. {motivo}'
            ).strip()[:300]
        elif modelo.variaveis != esperadas:
            modelo.erro_texto = (
                f'O modelo tem {modelo.variaveis} variável(is), e esta ocasião preenche '
                f'{esperadas}: {", ".join(EVENTOS[modelo.evento]["variaveis"])}.'
            )[:300]
    modelo.save()
    return modelo_aprovado(modelo)
