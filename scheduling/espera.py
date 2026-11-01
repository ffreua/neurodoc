"""A lista de espera da agenda: incluir, ordenar, puxar para um horário, retirar.

**Toda mudança de ordem passa por uma trava por clínica** (`_travar`), e é
ela, e não uma restrição `UNIQUE` em `posicao`, que mantém a sequência 1, 2,
3… Duas secretárias arrastando nomes ao mesmo tempo, sem a trava, leriam a
mesma lista, calculariam cada uma a sua e gravariam duas posições 3. Com
`UNIQUE` a renumeração inteira, que é como se move um nome, violaria a
restrição no meio do `UPDATE`.

A posição vale **entre as que aguardam** e na clínica inteira. O filtro por
médico mostra um recorte na mesma ordem, e subir um nome no recorte é
trocá-lo de lugar com o vizinho **visível** — não com o da linha de cima de
uma lista que a pessoa não está vendo.

Quem sai da lista (agendado ou retirado) perde a posição, e as de baixo
sobem: a secretária lê "3º" como "o terceiro a ser chamado", e um buraco ali
seria um nome que não existe.
"""

from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import EsperaStatus, PacienteEmEspera


class EsperaError(Exception):
    """Recusa com mensagem para a tela, em português."""


def _travar(tenant_id):
    """Trava a lista desta clínica até o fim da transação."""
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
            [f'espera:{tenant_id}'],
        )


def _aguardando(tenant_id):
    return (
        PacienteEmEspera.objects
        .filter(tenant_id=tenant_id, status=EsperaStatus.AGUARDANDO)
        .order_by('posicao', 'created_at', 'id')
    )


def _renumerar(tenant_id, ordem=None):
    """Grava 1..n na ordem dada (ou na atual). Só toca em quem mudou."""
    linhas = list(ordem) if ordem is not None else list(_aguardando(tenant_id))
    mudaram = []
    for numero, linha in enumerate(linhas, start=1):
        if linha.posicao != numero:
            linha.posicao = numero
            mudaram.append(linha)
    if mudaram:
        PacienteEmEspera.objects.bulk_update(mudaram, ['posicao'])
    return linhas


def _auditar(context, acao, entrada, **meta):
    record_audit_event(
        context.user_id, context.tenant_id, f'scheduling.espera_{acao}',
        object_type='espera', object_id=entrada.id, outcome='success',
        integrity_metadata=meta or None,
    )


def lista(tenant_id, physician_membership_id=None, incluir_encerradas=False):
    """A lista como a tela mostra: aguardando em ordem, com o recorte por médico.

    No recorte de um médico entram também as esperas de "qualquer médico" —
    são as mesmas que o modal de marcar oferece na agenda dele.
    """
    from django.db.models import Q

    consulta = (
        PacienteEmEspera.objects
        .filter(tenant_id=tenant_id)
        .select_related('patient', 'physician_membership__user', 'appointment')
        .prefetch_related('patient__contacts')
    )
    if physician_membership_id:
        consulta = consulta.filter(
            Q(physician_membership_id=physician_membership_id)
            | Q(physician_membership__isnull=True)
        )
    if incluir_encerradas:
        # Aguardando primeiro, na ordem; depois o histórico, do mais recente.
        aguardando = list(consulta.filter(status=EsperaStatus.AGUARDANDO)
                          .order_by('posicao', 'created_at', 'id'))
        encerradas = list(consulta.exclude(status=EsperaStatus.AGUARDANDO)
                          .order_by('-resolvido_em', '-created_at')[:200])
        return aguardando + encerradas
    return list(consulta.filter(status=EsperaStatus.AGUARDANDO)
                .order_by('posicao', 'created_at', 'id'))


@transaction.atomic
def incluir(context, patient, physician_membership=None, appointment_type='',
            observacao='', ator=None):
    """Põe o paciente no fim da lista."""
    _travar(context.tenant_id)
    if patient.tenant_id != context.tenant_id:
        raise EsperaError('Paciente não encontrado nesta organização.')
    if physician_membership is not None and physician_membership.tenant_id != context.tenant_id:
        raise EsperaError('Médico não encontrado nesta organização.')
    if _aguardando(context.tenant_id).filter(patient=patient).exists():
        raise EsperaError(f'{patient.full_name} já está na lista de espera.')
    ultima = _aguardando(context.tenant_id).order_by('-posicao').values_list(
        'posicao', flat=True).first() or 0
    entrada = PacienteEmEspera(
        tenant_id=context.tenant_id, patient=patient,
        physician_membership=physician_membership,
        appointment_type=appointment_type or '',
        observacao=(observacao or '').strip()[:255],
        posicao=ultima + 1, criado_por=ator,
    )
    entrada.full_clean()
    entrada.save()
    _auditar(context, 'incluida', entrada)
    return entrada


def _relida_aguardando(context, entrada):
    """A linha como está no banco, ou a recusa se já saiu da lista."""
    atual = PacienteEmEspera.objects.filter(
        tenant_id=context.tenant_id, id=entrada.id,
    ).select_for_update().first()
    if atual is None or atual.status != EsperaStatus.AGUARDANDO:
        raise EsperaError('Este paciente já saiu da lista de espera.')
    return atual


@transaction.atomic
def mover_para(context, entrada, posicao):
    """Leva o nome à posição dada (1 = primeiro); os outros abrem espaço."""
    _travar(context.tenant_id)
    entrada = _relida_aguardando(context, entrada)
    linhas = [linha for linha in _aguardando(context.tenant_id) if linha.id != entrada.id]
    destino = max(1, min(int(posicao), len(linhas) + 1))
    linhas.insert(destino - 1, entrada)
    _renumerar(context.tenant_id, linhas)
    _auditar(context, 'movida', entrada, posicao=destino)
    return destino


@transaction.atomic
def mover_vizinho(context, entrada, direcao, physician_membership_id=None):
    """Sobe ou desce um lugar **no recorte que a pessoa está vendo**.

    No recorte de um médico, o vizinho é o de cima (ou de baixo) entre as
    esperas dele e as de qualquer médico — trocar com uma linha invisível
    pareceria um clique que não fez nada.
    """
    if direcao not in ('subir', 'descer'):
        raise EsperaError('Direção inválida.')
    _travar(context.tenant_id)
    entrada = _relida_aguardando(context, entrada)
    todas = _renumerar(context.tenant_id)
    visiveis = [
        linha for linha in todas
        if not physician_membership_id
        or linha.physician_membership_id in (None, physician_membership_id)
        or linha.id == entrada.id
    ]
    indice = next(i for i, linha in enumerate(visiveis) if linha.id == entrada.id)
    alvo = indice - 1 if direcao == 'subir' else indice + 1
    if alvo < 0 or alvo >= len(visiveis):
        return entrada.posicao
    vizinho = visiveis[alvo]
    a = next(i for i, linha in enumerate(todas) if linha.id == entrada.id)
    b = next(i for i, linha in enumerate(todas) if linha.id == vizinho.id)
    todas[a], todas[b] = todas[b], todas[a]
    _renumerar(context.tenant_id, todas)
    _auditar(context, 'movida', entrada, posicao=b + 1)
    return b + 1


@transaction.atomic
def editar(context, entrada, physician_membership=None, appointment_type='', observacao=''):
    """Muda médico, tipo pretendido e observação. A posição não muda aqui."""
    _travar(context.tenant_id)
    entrada = _relida_aguardando(context, entrada)
    if physician_membership is not None and physician_membership.tenant_id != context.tenant_id:
        raise EsperaError('Médico não encontrado nesta organização.')
    entrada.physician_membership = physician_membership
    entrada.appointment_type = appointment_type or ''
    entrada.observacao = (observacao or '').strip()[:255]
    entrada.full_clean()
    entrada.save()
    _auditar(context, 'editada', entrada)
    return entrada


@transaction.atomic
def retirar(context, entrada, motivo='', ator=None):
    """Tira da lista sem horário: desistiu, resolveu em outro lugar, engano."""
    _travar(context.tenant_id)
    entrada = _relida_aguardando(context, entrada)
    entrada.status = EsperaStatus.RETIRADO
    entrada.motivo_saida = (motivo or '').strip()[:255]
    entrada.resolvido_em = timezone.now()
    entrada.resolvido_por = ator
    entrada.posicao = 0
    entrada.full_clean()
    entrada.save()
    _renumerar(context.tenant_id)
    _auditar(context, 'retirada', entrada)
    return entrada


def para_puxar(context, espera_id, physician_membership):
    """A espera que o modal mandou puxar, travada, ou a recusa.

    Chamada **dentro** da transação da reserva (`QuickBookingView`): se a
    consulta não nascer, a espera continua como estava; se duas pessoas
    puxarem o mesmo nome ao mesmo tempo, a segunda encontra a linha já
    encerrada e é recusada antes de marcar um segundo horário.
    """
    _travar(context.tenant_id)
    entrada = PacienteEmEspera.objects.filter(
        tenant_id=context.tenant_id, id=espera_id,
    ).select_related('patient', 'physician_membership__user').select_for_update(
        of=('self',),
    ).first()
    if entrada is None or entrada.status != EsperaStatus.AGUARDANDO:
        raise EsperaError(
            'Este paciente já saiu da lista de espera — talvez outra pessoa o tenha agendado agora.'
        )
    if entrada.physician_membership_id not in (None, physician_membership.id):
        medico = entrada.physician_membership.user.get_full_name() or 'outro médico'
        raise EsperaError(f'{entrada.patient.full_name} espera por horário com {medico}.')
    return entrada


def marcar_agendada(context, entrada, appointment, ator=None):
    """Encerra a espera puxada, ligada à consulta. Dentro da transação da reserva."""
    entrada.status = EsperaStatus.AGENDADO
    entrada.appointment = appointment
    entrada.resolvido_em = timezone.now()
    entrada.resolvido_por = ator
    entrada.posicao = 0
    entrada.full_clean()
    entrada.save()
    _renumerar(context.tenant_id)
    _auditar(context, 'agendada', entrada)
    return entrada


def opcoes_do_modal(tenant_id, physician_membership_id):
    """O que o modal de marcar oferece: as esperas deste médico e de qualquer um."""
    from django.db.models import Q

    return list(
        _aguardando(tenant_id)
        .filter(Q(physician_membership_id=physician_membership_id)
                | Q(physician_membership__isnull=True))
        .select_related('patient')
        [:100]
    )


def esperando(tenant_id, patient_id):
    """A espera em aberto do paciente, se houver — para o aviso após marcar."""
    return _aguardando(tenant_id).filter(patient_id=patient_id).first()
