"""Avisos no celular (Web Push) — o aplicativo instalado, Etapa 2.

**O mesmo arquivo nos dois produtos** (NeuroDoc e ProntDoc). Decisões em
`docs/homologation/pwa.md`; o protocolo em `notifications.webpush`.

O que chega ao aparelho, por decisão do titular (2026-11-27): tudo que vai
ao sino, a mensagem nova da equipe e o pedido ou o exame enviado pelo
portal. E **só o tipo do aviso** — "Resultado da IA pronto", nunca o nome
do paciente. A notificação aparece na tela bloqueada de um celular que fica
na mesa, é emprestado e é roubado; quem toca nela cai no sistema, que pede
o login e mostra o resto. Por isso o texto sai de `TEXTOS`, escrito aqui, e
nunca de `Notification.sanitized_title`, que nomeia o paciente.

Três fronteiras, todas em `check_push`:

- **o envio é do worker** (`tasks.enviar_push`), como o SMS e o e-mail
  (`CLAUDE.md` §2): o serviço de push pode demorar, e a requisição de quem
  gerou o aviso não espera por ele;
- **o endereço de entrega é de uma lista fechada** (`SERVICOS`). Ele vem
  do navegador, e o worker faz um `POST` para ele: aceitar qualquer
  `https://` faria do worker, que está dentro da rede do banco e do Redis,
  um carteiro para o endereço que o usuário escolher;
- **a chave privada nunca sai do servidor.** O par VAPID é gerado aqui na
  primeira vez e guardado cifrado na configuração da instalação, como a
  chave da IA reserva. Não é segredo do Swarm de propósito: um segredo novo
  no `docker-stack.yml` teria de existir na VPS antes do deploy, e o
  `stack deploy` falharia sem ele.
"""

import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Os serviços de push dos navegadores. Sufixo do nome do servidor; o
#: endereço tem de ser `https`, sem porta e sem usuário.
SERVICOS = (
    'fcm.googleapis.com',            # Chrome, Edge, Android
    'android.googleapis.com',
    'push.apple.com',                # Safari e o app instalado no iPhone
    'push.services.mozilla.com',     # Firefox
    'notify.windows.com',            # Edge antigo
)

#: Aparelhos por pessoa. Inscrição nova além disso tira a mais antiga: o
#: celular trocado não avisa que saiu, e a lista cresceria para sempre.
APARELHOS_POR_PESSOA = 10

#: Falhas seguidas (fora o 404/410, que apaga na hora) antes de desistir de
#: um aparelho.
FALHAS_PARA_DESISTIR = 5

#: O que a notificação diz, por tipo. O tipo do sino é o `kind` da
#: `Notification`; os outros três nascem aqui. Tipo novo no sino sem texto
#: aqui sai com `TEXTO_PADRAO` — genérico, e nunca vazio nem com o título.
TEXTOS = {
    'ai_job_succeeded': 'Resultado da IA pronto para revisão.',
    'ai_job_failed': 'A IA não conseguiu concluir um pedido.',
    'chat_reply_ready': 'O assistente respondeu.',
    'report_export_ready': 'Sua exportação está pronta.',
    'delivery_pending_contact': 'Um documento ficou sem contato para entrega.',
    'equipe': 'Nova mensagem da equipe.',
    'portal_pedido': 'Novo pedido pelo portal do paciente.',
    'portal_exame': 'Novo exame enviado pelo portal do paciente.',
    'teste': 'Os avisos estão funcionando neste aparelho.',
    'comunicado': 'Novo comunicado.',
}
TEXTO_PADRAO = 'Você tem um novo aviso.'


def ligado():
    """Os avisos no celular estão ligados nesta instalação?

    Dependem do worker do aplicativo: é ele quem recebe o aviso e o mostra,
    e o botão de emergência dele (`PWA_SERVICE_WORKER=False`) desregistra o
    worker — e com ele a inscrição — em cada aparelho. `PWA_PUSH=False`
    desliga só os avisos, e a tela sem internet continua.
    """
    from base.pwa import worker_ligado

    return worker_ligado() and bool(getattr(settings, 'PWA_PUSH', True))


def texto(tipo):
    return TEXTOS.get(tipo, TEXTO_PADRAO)


# ------------------------------------------------------------------ chaves

def _assunto():
    """O `sub` do VAPID: quem o serviço de push procura se algo der errado.

    A Apple recusa o aviso sem ele, e só aceita `mailto:` ou `https:`.
    """
    from email.utils import parseaddr

    endereco = parseaddr(getattr(settings, 'DEFAULT_FROM_EMAIL', '') or '')[1]
    if endereco and '@' in endereco:
        return f'mailto:{endereco}'
    return getattr(settings, 'PUBLIC_BASE_URL', '') or 'mailto:suporte@localhost'


def chave_publica():
    """A chave pública VAPID, criando o par na primeira vez."""
    return _chaves()[0]


def _chaves():
    from base.crypto import decrypt_secret, encrypt_secret
    from base.models import InstallationSettings

    from . import webpush

    linha = InstallationSettings.carregar()
    if linha.push_vapid_publica:
        return linha.push_vapid_publica, (
            lambda: decrypt_secret(linha.push_vapid_privada_cifrada, linha.push_vapid_privada_meta)
        )
    with transaction.atomic():
        # Trava a linha: duas telas abertas ao mesmo tempo na instalação
        # nova gerariam dois pares, e a inscrição feita com o primeiro
        # deixaria de funcionar quando o segundo fosse gravado por cima.
        linha = InstallationSettings.objects.select_for_update().get(pk=linha.pk)
        if not linha.push_vapid_publica:
            privada, publica = webpush.gerar_chaves()
            cifrada, meta = encrypt_secret(privada)
            linha.push_vapid_publica = publica
            linha.push_vapid_privada_cifrada = cifrada
            linha.push_vapid_privada_meta = meta
            linha.save(update_fields=['push_vapid_publica', 'push_vapid_privada_cifrada',
                                      'push_vapid_privada_meta', 'updated_at'])
    return linha.push_vapid_publica, (
        lambda: decrypt_secret(linha.push_vapid_privada_cifrada, linha.push_vapid_privada_meta)
    )


# ------------------------------------------------------------------ inscrição

class InscricaoRecusada(ValueError):
    """O navegador mandou algo que não é uma inscrição de push utilizável."""


def endereco_aceito(endpoint):
    try:
        partes = urlsplit(endpoint or '')
    except ValueError:
        return False
    host = (partes.hostname or '').lower()
    return (
        partes.scheme == 'https' and partes.port is None and not partes.username
        and len(endpoint) <= 1000
        and any(host == s or host.endswith('.' + s) for s in SERVICOS)
    )


def inscrever(user, dados, aparelho=''):
    """Grava (ou atualiza) a inscrição deste aparelho para esta pessoa.

    O endereço é único: se outra pessoa já tinha se inscrito neste mesmo
    navegador, a inscrição passa a ser de quem está entrando agora — o
    aparelho é um só, e os avisos têm de ir para quem está com ele.
    """
    from . import webpush
    from .models import PushSubscription

    endpoint = (dados or {}).get('endpoint') or ''
    chaves = (dados or {}).get('keys') or {}
    p256dh, auth = chaves.get('p256dh') or '', chaves.get('auth') or ''
    if not endereco_aceito(endpoint):
        raise InscricaoRecusada('Endereço de entrega não reconhecido.')
    if not webpush.chave_do_aparelho_valida(p256dh, auth):
        raise InscricaoRecusada('Chave do aparelho inválida.')
    inscricao, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={'user': user, 'p256dh': p256dh, 'auth': auth,
                  'aparelho': (aparelho or '')[:120], 'falhas': 0},
    )
    excedentes = list(
        PushSubscription.objects.filter(user=user).order_by('-created_at')
        .values_list('pk', flat=True)[APARELHOS_POR_PESSOA:]
    )
    if excedentes:
        PushSubscription.objects.filter(pk__in=excedentes).delete()
    return inscricao


def remover(user, endpoint):
    from .models import PushSubscription

    return PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()[0]


def aparelho_do_navegador(user_agent):
    """Um rótulo curto para a lista de aparelhos — nunca o User-Agent inteiro.

    O texto completo identifica versão de sistema e de navegador, o que não
    ajuda ninguém a reconhecer o próprio celular e serve para rastrear.
    """
    ua = user_agent or ''
    sistema = next((nome for marca, nome in (
        ('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'),
        ('Windows', 'Windows'), ('Mac OS', 'Mac'), ('Linux', 'Linux'),
    ) if marca in ua), 'Aparelho')
    navegador = next((nome for marca, nome in (
        ('Edg/', 'Edge'), ('Firefox/', 'Firefox'), ('Chrome/', 'Chrome'),
        ('CriOS/', 'Chrome'), ('Safari/', 'Safari'),
    ) if marca in ua), '')
    return f'{sistema} · {navegador}' if navegador else sistema


# ------------------------------------------------------------------ disparo

def avisar(user_ids, tipo, url='', *, tag='', ttl=86400):
    """Agenda o aviso no celular de cada pessoa — depois do commit.

    Depois do commit pelo mesmo motivo do chat da equipe: o aviso de algo
    que um erro de banco desfaz chegaria ao celular de alguém que tocaria
    nele e não encontraria nada. A pergunta "alguém aqui tem aparelho?" é
    feita antes de enfileirar, para a clínica que não usa os avisos não
    ganhar uma tarefa por notificação.
    """
    ids = sorted({str(u) for u in user_ids if u})
    if not ids or not ligado():
        return

    def _enfileirar():
        from .models import PushSubscription
        from .tasks import enviar_push

        if PushSubscription.objects.filter(user_id__in=ids).exists():
            enviar_push.delay(ids, tipo, url, tag, ttl)

    transaction.on_commit(_enfileirar)


def avisar_do_sino(user_ids, kind):
    """O aviso que acompanha cada linha nova do sino."""
    avisar(user_ids, kind, reverse('notifications:list'), tag=f'sino-{kind}')


def avisar_portal(tenant, tipo):
    """Pedido ou exame do portal: quem lê o prontuário naquela clínica.

    A mesma capacidade que abre Portal → Solicitações e Exames enviados
    (`base.context_processors._portal_badge`): o aviso não pode chamar para
    uma tela que a pessoa não abre.
    """
    from tenancy.permissions import Capability

    from .services import _members_with

    destino = ('documents:request-queue' if tipo == 'portal_pedido'
               else 'documents:portal-exams')
    ids = [m.user_id for m in _members_with(tenant, Capability.READ_CLINICAL)]
    avisar(ids, tipo, reverse(destino), tag=tipo)


# ------------------------------------------------------------------ envio (worker)

def enviar(user_ids, tipo, url='', tag='', ttl=86400, *, somente=None, titulo=None, corpo=None):
    """Manda o aviso a cada aparelho inscrito destas pessoas. Roda no worker.

    Devolve `{'enviados': n, 'removidos': n, 'falhas': n}`. Um aparelho que
    falha não impede os outros; 404 e 410 querem dizer que a inscrição
    acabou (app desinstalado, permissão retirada) e a linha sai na hora.
    """
    import httpx

    from . import webpush
    from .models import PushSubscription

    resultado = {'enviados': 0, 'removidos': 0, 'falhas': 0}
    if not ligado():
        return resultado
    consulta = PushSubscription.objects.filter(user_id__in=user_ids)
    if somente is not None:
        consulta = consulta.filter(pk__in=somente)
    inscricoes = list(consulta)
    if not inscricoes:
        return resultado
    _, privada = _chaves()
    privada = privada()
    assunto = _assunto()
    from base.pwa import PRODUTO

    # `titulo` e `corpo` próprios só o comunicado do console usa
    # (`notifications.comunicados`): é o único aviso cujo texto não é do tipo,
    # e é escrito pela casa, nunca tirado de dado de paciente.
    mensagem = json.dumps({
        'titulo': titulo or PRODUTO, 'corpo': corpo or texto(tipo),
        'url': url if url.startswith('/') and not url.startswith('//') else '/app/',
        'tag': tag or tipo,
    }, ensure_ascii=False).encode('utf-8')

    with httpx.Client(timeout=10, follow_redirects=False) as cliente:
        for inscricao in inscricoes:
            if not endereco_aceito(inscricao.endpoint):
                # Linha anterior a uma mudança da lista: não sai daqui.
                inscricao.delete()
                resultado['removidos'] += 1
                continue
            try:
                cabecalhos, corpo = webpush.montar_pedido(
                    inscricao.endpoint, inscricao.p256dh, inscricao.auth, mensagem,
                    privada, assunto, ttl=ttl, topico=_topico(tag or tipo),
                )
                resposta = cliente.post(inscricao.endpoint, headers=cabecalhos, content=corpo)
            except (httpx.HTTPError, ValueError) as exc:
                _falhou(inscricao, type(exc).__name__)
                resultado['falhas'] += 1
                continue
            if resposta.status_code in (200, 201, 202):
                PushSubscription.objects.filter(pk=inscricao.pk).update(
                    falhas=0, ultimo_envio_em=timezone.now())
                resultado['enviados'] += 1
            elif resposta.status_code in (404, 410):
                inscricao.delete()
                resultado['removidos'] += 1
            else:
                _falhou(inscricao, f'HTTP {resposta.status_code}')
                resultado['falhas'] += 1
    return resultado


def _topico(tag):
    import re

    return re.sub(r'[^A-Za-z0-9_-]', '-', tag)[:32]


def _falhou(inscricao, motivo):
    from .models import PushSubscription

    # Só o servidor do serviço no log: o endereço inteiro é a credencial de
    # entrega daquele aparelho.
    logger.warning('push: falha ao entregar em %s (%s)',
                   urlsplit(inscricao.endpoint).hostname, motivo)
    falhas = inscricao.falhas + 1
    if falhas >= FALHAS_PARA_DESISTIR:
        inscricao.delete()
    else:
        PushSubscription.objects.filter(pk=inscricao.pk).update(falhas=falhas)
