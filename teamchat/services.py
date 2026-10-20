"""As regras do chat da equipe. Só este módulo escreve nas três tabelas.

A razão de haver um módulo em vez de lógica nas views é o contador
denormalizado de `ConversationMember.unread_count`: uma view que criasse
uma `Message` sem passar por aqui deixaria a badge do cabeçalho mentindo
para sempre, e o defeito só apareceria como "diz que tem 3 e não tem".
`checks/check_mensagens.py` confere que a soma bate com a contagem real.
"""

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from tenancy.models import Membership, MembershipStatus, Role

from . import presence, streaming
from .models import MAX_BODY, Conversation, ConversationMember, Message, direct_key_for

#: Quantas mensagens a janela carrega ao abrir uma conversa. O resto sobe
#: por rolagem — carregar a conversa inteira de um ano custaria segundos
#: numa janela que a pessoa abriu para escrever uma linha.
PAGE_SIZE = 50

#: Quanto tempo uma mensagem da equipe vive. O chat é recado interno, não
#: prontuário (o aviso na janela diz isso), e não tem guarda legal: o que
#: precisa ficar vai na evolução do atendimento. Guardado para sempre, ele
#: viraria um segundo prontuário informal, sem assinatura e sem a guarda do
#: registro clínico -- e com dado de paciente dentro. Setenta e duas horas
#: cobrem o fim de semana: o recado de sexta à tarde ainda está lá na
#: segunda de manhã.
RETENCAO_HORAS = 72

_ROLE_LABELS = dict(Role.choices)


class ChatError(Exception):
    """Recusa esperada, com texto que pode ir para a tela."""


def display_name(user):
    return user.get_full_name() or user.email


def role_labels(roles):
    return [_ROLE_LABELS.get(r, r) for r in (roles or [])]


# --------------------------------------------------------------- colegas

def colleagues(tenant_id, me_user_id):
    """Vínculos ativos da clínica, menos o meu.

    Vínculo **ativo**, e não usuário: quem foi revogado não aparece na
    lista e não pode receber mensagem nova. É a mesma pergunta que o
    `AccessContext` faz do outro lado, o que impede a lista de oferecer um
    destinatário que o envio depois recusaria.
    """
    return (
        Membership.objects
        .filter(tenant_id=tenant_id, status=MembershipStatus.ACTIVE)
        .exclude(user_id=me_user_id)
        .select_related('user')
        .order_by('user__first_name', 'user__last_name', 'user__email')
    )


def _is_active_member(tenant_id, user_id):
    return Membership.objects.filter(
        tenant_id=tenant_id, user_id=user_id, status=MembershipStatus.ACTIVE,
    ).exists()


# ------------------------------------------------------------- conversas

@transaction.atomic
def open_direct(tenant_id, me_user_id, other_user_id, created_by_id=None):
    """A conversa entre duas pessoas, criando-a se ainda não existir.

    Recusa quem não tem vínculo ativo nesta clínica — é aqui que o
    isolamento entre inquilinos é feito para o chat. Sem esta verificação,
    um id de usuário de outra clínica no corpo do POST abriria uma
    conversa através da fronteira, e o `TenantModel` não impediria: a
    conversa nasceria no inquilino certo, com um participante que não é
    dele.
    """
    if str(other_user_id) == str(me_user_id):
        raise ChatError('Não dá para conversar consigo mesmo.')
    if not _is_active_member(tenant_id, other_user_id):
        raise ChatError('Esta pessoa não tem vínculo ativo nesta organização.')

    chave = direct_key_for(me_user_id, other_user_id)
    conversa = Conversation.objects.filter(tenant_id=tenant_id, direct_key=chave).first()
    if conversa is not None:
        return conversa

    conversa = Conversation.objects.create(
        tenant_id=tenant_id, direct_key=chave, created_by_id=created_by_id or me_user_id,
    )
    ConversationMember.objects.bulk_create([
        ConversationMember(tenant_id=tenant_id, conversation=conversa, user_id=me_user_id),
        ConversationMember(tenant_id=tenant_id, conversation=conversa, user_id=other_user_id),
    ])
    return conversa


def membership_in(tenant_id, conversation_id, user_id):
    """A linha de participação desta pessoa nesta conversa, ou `None`.

    É o porteiro de toda leitura e escrita de conversa: um id de conversa
    adivinhado não abre nada, porque não existe linha ligando quem pediu a
    ela. Filtra por inquilino também, e não só pela conversa — cinto e
    suspensório sobre a chave estrangeira composta.
    """
    return (
        ConversationMember.objects
        .select_related('conversation')
        .filter(tenant_id=tenant_id, conversation_id=conversation_id, user_id=user_id)
        .first()
    )


def messages_of(tenant_id, conversation_id, desde=None, apagada_em=None):
    """As mensagens da conversa: as últimas `PAGE_SIZE`, ou o que chegou
    depois de `desde`.

    `desde` é o carimbo da última mensagem que o cliente já tem. Hoje a
    janela não o usa: ela recarrega as últimas `PAGE_SIZE` ao abrir a
    conversa, e a entrega ao vivo é do SSE, que reconecta sozinho com
    `Last-Event-ID`. Fica como a saída para o buraco que o Redis não cobre
    — ele guarda os eventos por uma hora e não é a fonte da verdade — e
    está anotado aqui como não usado para que ninguém o leia como se
    estivesse.
    """
    # O que passou das 72 horas some da janela já, sem esperar a limpeza de
    # hora em hora apagar do banco; e o que a pessoa apagou some só dela.
    piso = limite_de_retencao()
    if apagada_em is not None and apagada_em > piso:
        piso = apagada_em
    consulta = Message.objects.filter(
        tenant_id=tenant_id, conversation_id=conversation_id, created_at__gt=piso,
    )
    if desde is not None:
        return list(consulta.filter(created_at__gt=desde).select_related('sender'))
    # Últimas N em ordem cronológica: a consulta desce por data e a lista
    # é invertida em memória. `ORDER BY ... ASC LIMIT` traria as primeiras
    # mensagens da conversa, que é o oposto do que a janela mostra.
    recentes = list(
        consulta.select_related('sender').order_by('-created_at', '-id')[:PAGE_SIZE]
    )
    recentes.reverse()
    return recentes


# ----------------------------------------------------------------- envio

@transaction.atomic
def send(tenant_id, conversation, sender_user_id, body):
    """Grava a mensagem, acerta os contadores e avisa quem está com a
    janela aberta — nesta ordem, que é a que importa.

    O aviso sai depois do commit (`on_commit`) e não faz parte da
    transação: publicar no Redis antes de gravar entregaria na tela uma
    linha que um erro de banco depois desfaria, e a pessoa teria lido uma
    mensagem que não existe.
    """
    texto = (body or '').strip()
    if not texto:
        raise ChatError('Mensagem vazia.')
    if len(texto) > MAX_BODY:
        raise ChatError(f'Mensagem longa demais (máximo de {MAX_BODY} caracteres).')

    mensagem = Message.objects.create(
        tenant_id=tenant_id, conversation=conversation,
        sender_id=sender_user_id, body=texto,
    )
    Conversation.objects.filter(pk=conversation.pk).update(
        last_message_at=mensagem.created_at,
    )
    participantes = list(
        ConversationMember.objects
        .filter(tenant_id=tenant_id, conversation=conversation)
        .values_list('user_id', flat=True)
    )
    # `F('unread_count') + 1` e não leitura-soma-gravação: duas mensagens
    # simultâneas para a mesma pessoa perderiam uma das duas contagens.
    ConversationMember.objects.filter(
        tenant_id=tenant_id, conversation=conversation,
    ).exclude(user_id=sender_user_id).update(unread_count=F('unread_count') + 1)

    payload = message_payload(mensagem)
    transaction.on_commit(lambda: _announce(tenant_id, participantes, payload))
    return mensagem


def _announce(tenant_id, participantes, payload):
    """Publica a mensagem na caixa de cada participante — inclusive na de
    quem enviou.

    Quem enviou recebe o próprio evento porque a mesma pessoa pode estar
    com duas abas abertas, e a segunda aba não tem outro jeito de saber o
    que a primeira escreveu. O cliente descarta o que já mostrou pelo id
    da mensagem.
    """
    for user_id in participantes:
        streaming.publish(tenant_id, user_id, 'mensagem', payload)


def message_payload(mensagem):
    return {
        'id': str(mensagem.id),
        'conversa': str(mensagem.conversation_id),
        'de': str(mensagem.sender_id),
        'nome': display_name(mensagem.sender),
        'texto': mensagem.body,
        'em': mensagem.created_at.isoformat(),
    }


# --------------------------------------------------------------- leitura

def mark_read(tenant_id, conversation_id, user_id):
    """Zera o não lido desta pessoa nesta conversa.

    `update` direto, sem carregar o objeto: é uma linha, e o valor novo
    não depende do antigo.
    """
    return ConversationMember.objects.filter(
        tenant_id=tenant_id, conversation_id=conversation_id, user_id=user_id,
    ).update(unread_count=0, last_read_at=timezone.now())


def apagar_conversa(tenant_id, conversation_id, user_id):
    """Apaga a conversa **para quem pediu**.

    Marca `cleared_at` e zera o que faltava ler. As mensagens continuam no
    banco para o colega até completarem 72 horas, quando a limpeza as apaga
    de vez. A trilha registra que a conversa foi apagada, sem texto nenhum:
    o recado interno não é prontuário e não vai para a auditoria.
    """
    from audit.services import record_audit_event

    agora = timezone.now()
    atualizados = ConversationMember.objects.filter(
        tenant_id=tenant_id, conversation_id=conversation_id, user_id=user_id,
    ).update(cleared_at=agora, unread_count=0, last_read_at=agora)
    if atualizados:
        record_audit_event(
            user_id, tenant_id, 'teamchat.conversation_cleared',
            object_type='conversation', object_id=conversation_id, outcome='success',
        )
    return bool(atualizados)


def limite_de_retencao():
    """O instante antes do qual mensagem nenhuma é mostrada nem guardada."""
    return timezone.now() - timezone.timedelta(hours=RETENCAO_HORAS)


def apagar_vencidas():
    """Apaga do banco as mensagens com mais de 72 horas.

    Roda de hora em hora (`teamchat.tasks.apagar_vencidas`). Três passos, e
    a ordem importa:

    1. apaga as mensagens vencidas;
    2. **refaz** o contador de não lidas de quem tinha alguma: mensagem que
       sumiu sem ser lida não pode continuar acendendo a badge do
       cabeçalho — o contador é denormalizado, e só aqui ele pode divergir;
    3. apaga a conversa que ficou sem mensagem nenhuma, com as
       participações. Ela renasce sozinha na próxima mensagem
       (`open_direct`), e guardada vazia só diria quem falou com quem.

    Devolve as contagens, para o log da tarefa.
    """
    limite = limite_de_retencao()
    with transaction.atomic():
        apagadas, _ = Message.objects.filter(created_at__lte=limite).delete()
        corrigidos = 0
        for membro in ConversationMember.objects.filter(unread_count__gt=0).select_for_update():
            desde = max(filter(None, [membro.last_read_at, membro.cleared_at, limite]))
            reais = Message.objects.filter(
                tenant_id=membro.tenant_id, conversation_id=membro.conversation_id,
                created_at__gt=desde,
            ).exclude(sender_id=membro.user_id).count()
            if reais != membro.unread_count:
                membro.unread_count = reais
                membro.save(update_fields=['unread_count'])
                corrigidos += 1
        # Só a vazia **antiga**: a conversa aberta agora, que ainda não teve
        # a primeira mensagem, não pode sumir entre o clique e o envio.
        vazias = list(
            Conversation.objects.filter(messages__isnull=True, created_at__lte=limite)
            .values_list('id', flat=True)
        )
        ConversationMember.objects.filter(conversation_id__in=vazias).delete()
        conversas, _ = Conversation.objects.filter(id__in=vazias).delete()
    return {'mensagens': apagadas, 'contadores': corrigidos, 'conversas': conversas}


def unread_total(tenant_id, user_id):
    """Quantas mensagens não lidas esta pessoa tem nesta clínica.

    Uma soma sobre as linhas de participação do usuário — que são poucas e
    estão indexadas por (tenant, user). É o número da badge ao lado do
    sino, e roda em toda requisição de `/app/`: por isso é uma soma de
    contadores, e não uma contagem de mensagens.
    """
    return (
        ConversationMember.objects
        .filter(tenant_id=tenant_id, user_id=user_id)
        .aggregate(total=Sum('unread_count'))['total'] or 0
    )


def state_for(tenant_id, user_id):
    """Tudo o que a janela precisa para desenhar a coluna da esquerda.

    Uma chamada só: colegas, quem está on-line, e quantas mensagens de
    cada um esperam resposta. Separar em três endpoints daria três idas ao
    servidor a cada sondagem para montar uma lista de dez pessoas.
    """
    online = presence.online_user_ids(tenant_id)
    minhas = {
        m.conversation_id: m
        for m in ConversationMember.objects.filter(tenant_id=tenant_id, user_id=user_id)
    }
    # Quem é o outro lado de cada conversa minha, numa consulta só.
    outro_lado = {}
    if minhas:
        for m in ConversationMember.objects.filter(
            tenant_id=tenant_id, conversation_id__in=list(minhas),
        ).exclude(user_id=user_id):
            outro_lado[str(m.user_id)] = m.conversation_id

    pessoas = []
    for vinculo in colleagues(tenant_id, user_id):
        chave = str(vinculo.user_id)
        conversa_id = outro_lado.get(chave)
        participacao = minhas.get(conversa_id) if conversa_id else None
        pessoas.append({
            'user_id': chave,
            'nome': display_name(vinculo.user),
            'papeis': role_labels(vinculo.roles),
            'online': chave in online,
            'conversa': str(conversa_id) if conversa_id else '',
            'nao_lidas': participacao.unread_count if participacao else 0,
        })
    return {
        # De quem é a sessão que fez esta requisição. O cliente compara com
        # o id que a página trouxe ao ser montada e descobre, com isso, que
        # alguém entrou com outra conta neste navegador — duas abas do
        # mesmo perfil dividem um cookie só, então a aba antiga passa a
        # falar pela conta nova e mostraria a lista de colegas errada, em
        # silêncio. É a diferença entre uma tela que mente e uma que avisa.
        'eu': str(user_id),
        'total': sum(p['nao_lidas'] for p in pessoas),
        'pessoas': pessoas,
    }
