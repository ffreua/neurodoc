"""Context shared by the Duralux application shell.

Everything here is derived from ``request.access_context`` and therefore
scoped to the tenant of the current request; nothing is cached across
requests. Outside ``/app/`` the processor returns the empty shell so
public pages (landing, authentication, document access) render without a
sidebar.
"""
from django.db.models import F
from django.urls import Resolver404, resolve

from tenancy.permissions import Capability

from .version import VERSION

#: Todas as capacidades declaradas, para o dicionário do template trazer
#: também as negadas — uma chave ausente e uma chave `False` se comportam
#: igual no template, mas a lista completa é o que permite conferir a
#: cobertura sem abrir o código.
_ALL_CAPABILITIES = frozenset(
    value for name, value in vars(Capability).items()
    if not name.startswith('_') and isinstance(value, str)
)


def _section(request):
    match = getattr(request, 'resolver_match', None)
    if match is None:
        # Context processors run before the view for some error paths.
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return ''
    return match.namespace or ''


def _view_name(request):
    """Nome da rota atual, para o menu distinguir irmãos do mesmo app.

    `documents` responde tanto pela assinatura quanto pela fila do portal;
    sem isto, abrir a fila acende o item errado no menu lateral.
    """
    match = getattr(request, 'resolver_match', None)
    return getattr(match, 'url_name', '') or ''


def _initials(user):
    parts = [p for p in (user.first_name, user.last_name) if p]
    if parts:
        return ''.join(p[0] for p in parts[:2]).upper()
    return (user.email or '?')[0].upper()


def shell(request):
    user = getattr(request, 'user', None)
    context = getattr(request, 'access_context', None)
    data = {
        # A versao do produto, em toda tela. Constante de modulo, sem
        # consulta: o rodape do aplicativo e o da pagina publica mostram a
        # mesma, e quem abre um chamado de suporte tem o numero a vista sem
        # precisar procurar.
        'nd_versao': VERSION,
        'nd_section': _section(request),
        'nd_view': _view_name(request),
        'nd_portal_requests': 0,
        'nd_portal_visible': False,
        'nd_tenant': None,
        'nd_clinic_has_logo': False,
        'nd_roles': [],
        'nd_unread_notifications': 0,
        'nd_unread_messages': 0,
        'nd_recent_notifications': (),
        'nd_user_initials': _initials(user) if user is not None and user.is_authenticated else '',
        'nd_can': {},
    }
    if context is None:
        return data

    from notifications.models import Notification
    from tenancy.models import Tenant

    mine = Notification.objects.filter(tenant_id=context.tenant_id, user_id=context.user_id)
    data['nd_tenant'] = Tenant.objects.filter(id=context.tenant_id).first()
    # Só se há logotipo: o menu decide entre a imagem da clínica e o escudo
    # genérico. `only` porque a linha do perfil traz endereço, aviso do
    # portal e mais — e isto roda em toda requisição de `/app/`.
    from tenancy.models import ClinicProfile

    data['nd_clinic_has_logo'] = ClinicProfile.objects.filter(
        tenant_id=context.tenant_id,
    ).exclude(logo_path='').exists()
    data['nd_roles'] = sorted(context.permissions)
    # Dicionário, e não conjunto: `{% if nd_can.read_clinical %}` com um nome
    # errado dá falso e **esconde** o item, enquanto uma verificação escrita
    # ao contrário o mostraria a quem não pode abri-lo. Errar para o lado de
    # esconder é o único erro aceitável aqui.
    #
    # Isto governa o que aparece, não o que é permitido: quem decide são as
    # views (`tenancy.permissions`). Menu escondido sem view protegida é
    # decoração; view protegida sem menu escondido é um 404 na cara de quem
    # clicou. As duas coisas juntas é que fazem sentido.
    data['nd_can'] = {
        name: context.can(name) for name in context.capabilities | _ALL_CAPABILITIES
    }
    data['nd_unread_notifications'] = mine.filter(read_at__isnull=True).count()
    # Mensagens da equipe: uma soma sobre as poucas linhas de participação
    # deste usuário, e não uma contagem na tabela de mensagens — ver o
    # comentário de `ConversationMember.unread_count`. É o que acende a
    # badge do botão ao lado do sino já na primeira renderização, sem
    # esperar a sondagem do JavaScript.
    from teamchat.services import unread_total

    data['nd_unread_messages'] = unread_total(context.tenant_id, context.user_id)
    # Não lidas primeiro, como na central. O sino mostra cinco linhas: se
    # ordenar só por data, cinco avisos lidos hoje escondem o pendente de
    # ontem — que é justamente o que ainda precisa de alguém.
    data['nd_recent_notifications'] = list(
        mine.order_by(F('read_at').asc(nulls_first=True), '-created_at')[:5]
    )
    data.update(_portal_badge(context))
    return data


def _portal_badge(context):
    """Quantos pedidos do portal esperam revisão, e se o item aparece.

    O menu só existe para quem pode abrir prontuário, e só quando há o que
    ver: portal publicado, ou fila com pedido pendente. A segunda condição
    importa porque despublicar o portal não apaga o que já chegou — sem
    ela, os pedidos recebidos ficariam sem porta de entrada no dia em que a
    clínica desligasse o formulário.

    A contagem custa um `COUNT` com índice em (tenant, status) e só roda
    para quem tem a capacidade clínica.
    """
    if not context.can(Capability.READ_CLINICAL):
        return {'nd_portal_requests': 0, 'nd_portal_visible': False}

    from documents.models import DocumentRequest, DocumentRequestStatus
    from tenancy.models import ClinicProfile

    abertos = DocumentRequest.objects.filter(
        tenant_id=context.tenant_id,
        status__in=[DocumentRequestStatus.RECEIVED, DocumentRequestStatus.IN_REVIEW],
    ).count()
    visivel = abertos > 0 or ClinicProfile.objects.filter(
        tenant_id=context.tenant_id, patient_portal_enabled=True,
    ).exists()
    return {'nd_portal_requests': abertos, 'nd_portal_visible': visivel}
