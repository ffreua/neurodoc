"""Quem recebe cada aviso, e o que ele diz.

Duas mudanças de fundo em relação à primeira versão:

**Destinatário por capacidade, não por papel.** `notify_role` escolhia por
`roles__overlap`, e o resultado era aviso que quem recebe não pode
atender: o pedido do portal ia para `('doctor', 'secretary')`, e a fila
exige capacidade clínica — a secretária recebia o aviso de que um paciente
pediu alguma coisa, ficava sabendo que aquele paciente pediu, e o link
respondia 404. `notify_capability` pergunta a `tenancy.permissions` o
mesmo que as views perguntam, então a caixa e a tela não divergem.

**O aviso nomeia o caso.** "Entrega pendente — verifique o cadastro de
contato do paciente" obrigava a adivinhar qual paciente. `context` carrega
nome e número de prontuário, e a tela os mostra.

O limite continua o mesmo: nome e número identificam, e **conteúdo clínico
não entra**. Quem tem vínculo ativo já vê o nome do paciente na agenda e
na lista; o que a caixa não pode fazer é contar o que foi escrito no
prontuário — ela é lida em toda requisição para montar o sino do
cabeçalho.
"""

from tenancy.models import Membership, MembershipStatus
from tenancy.permissions import capabilities_for
from tenancy.plans import has_clinical_ai

from .models import Notification


def patient_context(patient, **extra):
    """Os fatos que identificam o paciente numa linha de aviso.

    Número do prontuário junto com o nome porque homônimo existe, e porque
    é o número que se dita ao telefone e se procura na busca.
    """
    data = {
        'patient': patient.full_name,
        'record_number': patient.record_number or '',
    }
    data.update({k: v for k, v in extra.items() if v})
    return data


def _members_with(tenant, capability):
    """Vínculos ativos cuja capacidade calculada inclui `capability`.

    Calculado por vínculo, e não por consulta ao banco, porque a
    capacidade clínica depende de `PhysicianProfile` verificado — um
    filtro por `roles__contains=['doctor']` incluiria o médico recém
    convidado, que ainda não pode abrir nada.
    """
    membros = (
        Membership.objects
        .filter(tenant=tenant, status=MembershipStatus.ACTIVE)
        .select_related('user')
    )
    # Lido uma vez, fora da lista: o plano e da clinica, igual para todos
    # os vinculos dela, e perguntar por vinculo seria uma consulta por
    # membro para sempre chegar na mesma resposta.
    ia = has_clinical_ai(tenant.plan)
    return [
        m for m in membros
        if capability in capabilities_for(
            m.roles, clinically_enabled=m.can_practice_clinically(), ai_contracted=ia,
        )
    ]


def notify_capability(tenant, capability, kind, sanitized_title,
                      target_type='', target_id=None, context=None):
    """Avisa quem pode agir sobre isto.

    Devolve lista vazia quando ninguém na clínica tem a capacidade — o que
    é informação, não erro: uma clínica sem médico habilitado não tem quem
    revise pedido do portal, e inventar destinatário não resolveria.
    """
    destinatarios = _members_with(tenant, capability)
    return Notification.objects.bulk_create([
        Notification(
            tenant=tenant, user_id=m.user_id, kind=kind, sanitized_title=sanitized_title,
            target_type=target_type, target_id=target_id, context=context or {},
        )
        for m in destinatarios
    ])


def notify_role(tenant, roles, kind, sanitized_title, target_type='', target_id=None,
                context=None):
    """Avisa por papel.

    Mantida para o caso em que o destinatário é o papel mesmo, e não uma
    capacidade — mas prefira `notify_capability`: papel é como a pessoa foi
    cadastrada, capacidade é o que ela consegue abrir, e é a segunda que
    decide se o link funciona.
    """
    memberships = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__overlap=list(roles),
    )
    notifications = [
        Notification(
            tenant=tenant, user_id=m.user_id, kind=kind, sanitized_title=sanitized_title,
            target_type=target_type, target_id=target_id, context=context or {},
        )
        for m in memberships
    ]
    return Notification.objects.bulk_create(notifications)


def notify_user(tenant, user_id, kind, sanitized_title, target_type='', target_id=None,
                context=None):
    return Notification.objects.create(
        tenant=tenant, user_id=user_id, kind=kind, sanitized_title=sanitized_title,
        target_type=target_type, target_id=target_id, context=context or {},
    )


def mark_read(notification):
    from django.utils import timezone

    if notification.read_at is not None:
        return notification
    notification.read_at = timezone.now()
    notification.save(update_fields=['read_at'])
    return notification


def mark_all_read(tenant_id, user):
    """Marca como lidas todas as não lidas desta pessoa nesta clínica.

    Uma consulta de atualização, e não um laço: são as notificações de um
    usuário só, mas uma caixa que acumulou meses tem centenas de linhas, e
    salvar uma a uma é uma transação por linha.

    Escopo por inquilino de propósito. Quem trabalha em duas clínicas tem
    duas caixas, e limpar a de uma não pode apagar o aviso pendente da
    outra — que é justamente o que ela não está olhando agora.
    """
    from django.utils import timezone

    return Notification.objects.filter(
        tenant_id=tenant_id, user=user, read_at__isnull=True,
    ).update(read_at=timezone.now())
