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

**Antecipar uma consulta já marcada** (2026-11-12). A recepção marca o
paciente na data possível e o põe na lista **pela agenda**, para chamá-lo
se abrir vaga antes. A espera guarda essa consulta (`consulta_marcada`), e
duas regras saem dela:

- puxado para um horário **anterior**, a consulta antiga é desmarcada na
  mesma transação, com o motivo — o paciente não fica com duas, e a vaga
  antiga volta à grade;
- chegado o dia da consulta sem antecipação, a espera se encerra sozinha
  (`encerrar_no_dia_da_consulta`, tarefa diária): ninguém mais precisa
  chamar quem já está sendo atendido.
"""

from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event
from patients.models import PatientStatus

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
        .select_related('patient', 'physician_membership__user', 'appointment', 'consulta_marcada')
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


#: Situações em que a consulta marcada ainda é uma consulta a antecipar.
SITUACOES_A_ANTECIPAR = ('scheduled', 'confirmed')


@transaction.atomic
def incluir(context, patient, physician_membership=None, appointment_type='',
            observacao='', ator=None, consulta_marcada=None):
    """Põe o paciente no fim da lista.

    Com `consulta_marcada`, é a inclusão pela agenda: o paciente já tem
    aquela consulta e espera uma vaga **antes** dela.
    """
    _travar(context.tenant_id)
    if consulta_marcada is not None:
        if (consulta_marcada.tenant_id != context.tenant_id
                or consulta_marcada.patient_id != patient.id):
            raise EsperaError('Consulta não encontrada para este paciente.')
        if consulta_marcada.status not in SITUACOES_A_ANTECIPAR:
            raise EsperaError('Só a consulta agendada ou confirmada pode ir para a lista de espera.')
        if timezone.localtime(consulta_marcada.starts_at).date() <= timezone.localdate():
            raise EsperaError('A consulta é hoje ou já passou: não há o que antecipar.')
    if patient.tenant_id != context.tenant_id:
        raise EsperaError('Paciente não encontrado nesta organização.')
    if physician_membership is not None and physician_membership.tenant_id != context.tenant_id:
        raise EsperaError('Médico não encontrado nesta organização.')
    if patient.status == PatientStatus.ARCHIVED:
        raise EsperaError(f'A ficha de {patient.full_name} está arquivada. Desarquive antes de pôr na lista.')
    if _aguardando(context.tenant_id).filter(patient=patient).exists():
        raise EsperaError(f'{patient.full_name} já está na lista de espera.')
    ultima = _aguardando(context.tenant_id).order_by('-posicao').values_list(
        'posicao', flat=True).first() or 0
    entrada = PacienteEmEspera(
        tenant_id=context.tenant_id, patient=patient,
        physician_membership=physician_membership,
        appointment_type=appointment_type or '',
        observacao=(observacao or '').strip()[:255],
        posicao=ultima + 1, criado_por=ator, consulta_marcada=consulta_marcada,
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
    # Ficha arquivada não marca horário por caminho nenhum (revisão de
    # 2026-11-02, W7): a espera continua à vista, com o aviso, para alguém
    # decidir — retirar da lista ou desarquivar —, e não é encerrada sozinha.
    if entrada.patient.status == PatientStatus.ARCHIVED:
        raise EsperaError(
            f'A ficha de {entrada.patient.full_name} está arquivada. Desarquive antes de marcar.'
        )
    if entrada.physician_membership_id not in (None, physician_membership.id):
        medico = entrada.physician_membership.user.get_full_name() or 'outro médico'
        raise EsperaError(f'{entrada.patient.full_name} espera por horário com {medico}.')
    return entrada


def marcar_agendada(context, entrada, appointment, ator=None):
    """Encerra a espera puxada, ligada à consulta. Dentro da transação da reserva.

    Se a espera era para antecipar uma consulta marcada e o horário novo vem
    **antes** dela, a antiga é desmarcada aqui mesmo — na transação da
    reserva, então ou as duas coisas acontecem, ou nenhuma. Devolve a
    consulta desmarcada (ou None), para a tela dizer o que fez.
    """
    from .services import cancel_appointment

    desmarcada = None
    antiga = entrada.consulta_marcada
    if (antiga is not None and antiga.status in SITUACOES_A_ANTECIPAR
            and antiga.id != appointment.id and appointment.starts_at < antiga.starts_at):
        quando = timezone.localtime(appointment.starts_at).strftime('%d/%m/%Y às %H:%M')
        desmarcada = cancel_appointment(
            antiga, context.user_id, reason=f'Antecipada pela lista de espera para {quando}.',
        )
    entrada.status = EsperaStatus.AGENDADO
    entrada.appointment = appointment
    entrada.resolvido_em = timezone.now()
    entrada.resolvido_por = ator
    entrada.posicao = 0
    entrada.full_clean()
    entrada.save()
    _renumerar(context.tenant_id)
    _auditar(context, 'agendada', entrada,
             **({'consulta_desmarcada': str(desmarcada.id)} if desmarcada else {}))
    return desmarcada


def opcoes_do_modal(tenant_id, physician_membership_id):
    """O que o modal de marcar oferece: as esperas deste médico e de qualquer um."""
    from django.db.models import Q

    return list(
        _aguardando(tenant_id)
        .filter(Q(physician_membership_id=physician_membership_id)
                | Q(physician_membership__isnull=True))
        .exclude(patient__status=PatientStatus.ARCHIVED)
        .select_related('patient')
        [:100]
    )


def esperando(tenant_id, patient_id):
    """A espera em aberto do paciente, se houver — para o aviso após marcar."""
    return _aguardando(tenant_id).filter(patient_id=patient_id).first()


@transaction.atomic
def devolver_a_lista(context, appointment, ator=None):
    """A consulta puxada da lista deixou de ser do paciente: ele volta ao topo.

    Até a revisão de 2026-11-02 (W6), trocar o paciente ou cancelar a
    consulta que veio da lista tirava a pessoa dela sem ninguém decidir: a
    espera ficava "agendada" apontando para um horário que não era mais
    dela. Volta ao **topo**, e não ao fim: ela já era a vez quando foi
    puxada. Devolve a espera reaberta, ou None se a consulta não veio da
    lista (ou se o paciente já voltou a aguardar por outro caminho).
    """
    _travar(context.tenant_id)
    entrada = PacienteEmEspera.objects.filter(
        tenant_id=context.tenant_id, appointment_id=appointment.id, status=EsperaStatus.AGENDADO,
    ).select_related('patient').select_for_update(of=('self',)).first()
    if entrada is None or entrada.patient.status == PatientStatus.ARCHIVED:
        return None
    if _aguardando(context.tenant_id).filter(patient_id=entrada.patient_id).exists():
        return None
    entrada.status = EsperaStatus.AGUARDANDO
    entrada.appointment = None
    entrada.resolvido_em = None
    entrada.resolvido_por = None
    entrada.posicao = 0
    entrada.full_clean()
    entrada.save()
    _renumerar(context.tenant_id, [entrada, *_aguardando(context.tenant_id).exclude(id=entrada.id)])
    _auditar(context, 'devolvida', entrada)
    return entrada


@transaction.atomic
def por_na_lista_ao_cancelar(context, appointment, ator=None):
    """O "pôr na lista de espera" do cancelamento: devolve, ou inclui no fim.

    Quem decide é quem cancela, pela caixa no modal: o paciente que
    desmarcou porque desistiu não volta para a lista sozinho.
    """
    devolvida = devolver_a_lista(context, appointment, ator=ator)
    if devolvida is not None:
        return devolvida, 'devolvida'
    return incluir(
        context, appointment.patient, physician_membership=appointment.physician_membership,
        appointment_type=appointment.type, observacao='Consulta cancelada.', ator=ator,
    ), 'incluida'


def da_consulta(tenant_id, appointment):
    """A espera em aberto do paciente deste horário, se houver — para o modal da agenda."""
    return (
        _aguardando(tenant_id).filter(patient_id=appointment.patient_id)
        .select_related('consulta_marcada').first()
    )


def encerrar_no_dia_da_consulta(hoje=None):
    """Tira da lista quem chegou ao dia da consulta que queria antecipar.

    Roda todo dia de madrugada (`scheduling.tasks.encerrar_esperas_do_dia`),
    em todas as clínicas — inclusive nos dias sem agenda, o que não muda
    nada: a regra é "a data da consulta chegou", e a consulta de sábado
    encerra a espera no sábado. A consulta desmarcada por outro caminho
    deixa a espera de pé: aí o paciente voltou a não ter horário, e é
    exatamente quem a lista existe para chamar.

    Devolve quantas esperas encerrou.
    """
    from types import SimpleNamespace

    hoje = hoje or timezone.localdate()
    vencidas = (
        PacienteEmEspera.objects
        .filter(status=EsperaStatus.AGUARDANDO, consulta_marcada__isnull=False,
                consulta_marcada__status__in=SITUACOES_A_ANTECIPAR)
        .select_related('consulta_marcada')
    )
    encerradas = 0
    for entrada in vencidas:
        dia = timezone.localtime(entrada.consulta_marcada.starts_at).date()
        if dia > hoje:
            continue
        contexto = SimpleNamespace(user_id=None, tenant_id=entrada.tenant_id)
        try:
            retirar(
                contexto, entrada,
                motivo=f'Chegou o dia da consulta marcada ({dia.strftime("%d/%m/%Y")}) sem antecipação.',
            )
            encerradas += 1
        except EsperaError:
            # Outra pessoa a tirou da lista agora mesmo; nada a fazer.
            continue
    return encerradas
