"""Serviços da agenda de exames: janelas, horários livres, reserva, realização.

## O dia da tela não é o dia da reserva

Tudo aqui é **instante** (datetime com fuso), e o dia só existe na tela.
Uma janela de segunda das 20h às 7h vira o intervalo [segunda 20h, terça
7h); a reserva das 21h às 7h é uma linha só, que aparece na segunda **e**
na terça. Por isso "o que há no dia D" é "o que **cruza** [D 00h, D+1
00h)", e "cabe na agenda" é "cabe dentro de uma janela inteira" — e a
janela que começou na véspera conta.

## Quem garante que não há dois exames no mesmo equipamento

O banco: `agenda_exames_reserva_sem_sobreposicao`, exclusão por recurso no
intervalo ocupado (`[início, fim + intervalo)`). A conferência em Python
dá a mensagem boa; a corrida entre duas recepcionistas, quem decide é a
restrição, e a perdedora recebe "o horário acabou de ser ocupado".
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record_audit_event

from . import lembretes
from .models import (
    DURACAO_MAXIMA_MINUTOS, OCUPAM, TRANSICOES, Bloqueio, Cobranca, EstadoReserva, Janela, Recurso, Reserva,
)


class ReservaRecusada(Exception):
    """Mensagem em português, para a tela."""


def _ocupacao(inicio, fim, intervalo):
    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    return DateTimeTZRange(inicio, fim + timedelta(minutes=intervalo or 0), bounds='[)')


def _no_dia(dia, hora):
    return timezone.make_aware(datetime.combine(dia, hora))


# ------------------------------------------------------------------ janelas

def janelas_que_comecam(recurso, dia):
    """As janelas vigentes que **começam** em `dia`, como instantes."""
    saida = []
    for j in recurso.janelas.all():
        if j.dia_semana != dia.weekday():
            continue
        if j.vigente_desde and j.vigente_desde > dia:
            continue
        if j.vigente_ate and j.vigente_ate < dia:
            continue
        inicio = _no_dia(dia, j.inicio)
        fim = _no_dia(dia + timedelta(days=1) if j.atravessa_meia_noite else dia, j.fim)
        saida.append((inicio, fim))
    return saida


def janelas_que_cruzam(recurso, dia):
    """As janelas que tocam o dia, inclusive a que veio da véspera."""
    comeco, fim_do_dia = _no_dia(dia, time.min), _no_dia(dia + timedelta(days=1), time.min)
    todas = janelas_que_comecam(recurso, dia - timedelta(days=1)) + janelas_que_comecam(recurso, dia)
    return sorted((a, b) for a, b in todas if a < fim_do_dia and b > comeco)


def _bloqueado(recurso, inicio, fim):
    return Bloqueio.objects.filter(recurso=recurso, inicio__lt=fim, fim__gt=inicio).first()


def cabe_na_agenda(recurso, inicio, fim):
    """`''` se cabe numa janela inteira e fora de bloqueio; senão, o motivo."""
    for dia in (timezone.localtime(inicio).date() - timedelta(days=1), timezone.localtime(inicio).date()):
        for a, b in janelas_que_comecam(recurso, dia):
            if a <= inicio and fim <= b:
                bloqueio = _bloqueado(recurso, inicio, fim)
                if bloqueio:
                    return f'A agenda está bloqueada nesse horário ({bloqueio.motivo}).'
                return ''
    return 'Fora do horário de atendimento desta agenda. Para marcar mesmo assim, use encaixe com o motivo.'


@dataclass(frozen=True)
class Horario:
    inicio: datetime
    fim: datetime


def horarios_livres(recurso, dia, agora=None):
    """Inícios livres do dia, com a duração padrão, em janelas que começam no dia.

    A janela que veio da véspera já ofereceu os horários dela no dia
    anterior; oferecer de novo aqui mostraria a mesma polissonografia como
    livre em dois dias da tela.
    """
    agora = agora or timezone.now()
    passo = timedelta(minutes=recurso.duracao_padrao + recurso.intervalo)
    duracao = timedelta(minutes=recurso.duracao_padrao)
    ocupadas = [
        (r.ocupacao.lower, r.ocupacao.upper)
        for r in Reserva.objects.filter(recurso=recurso, estado__in=[str(e) for e in OCUPAM])
        .filter(inicio__lt=_no_dia(dia + timedelta(days=2), time.min), fim__gt=_no_dia(dia - timedelta(days=1), time.min))
    ]
    bloqueios = [(b.inicio, b.fim) for b in Bloqueio.objects.filter(
        recurso=recurso, inicio__lt=_no_dia(dia + timedelta(days=2), time.min),
        fim__gt=_no_dia(dia - timedelta(days=1), time.min))]
    livres = []
    for a, b in janelas_que_comecam(recurso, dia):
        cursor = a
        while cursor + duracao <= b:
            fim = cursor + duracao
            fim_ocupado = fim + timedelta(minutes=recurso.intervalo)
            choca = any(x < fim_ocupado and y > cursor for x, y in ocupadas + bloqueios)
            if not choca and cursor > agora:
                livres.append(Horario(cursor, fim))
            cursor += passo
    return livres


def reservas_do_dia(recurso, dia):
    comeco, fim_do_dia = _no_dia(dia, time.min), _no_dia(dia + timedelta(days=1), time.min)
    return (
        Reserva.objects.filter(recurso=recurso, inicio__lt=fim_do_dia, fim__gt=comeco)
        .select_related('paciente', 'executante', 'cobertura__plan__insurer')
        .order_by('inicio')
    )


# ------------------------------------------------------------------ reserva

def _conferir_cobranca(paciente, cobranca, cobertura, dia):
    if cobranca == Cobranca.CONVENIO:
        if cobertura is None:
            raise ReservaRecusada('Escolha o convênio do paciente para um exame por convênio.')
        if cobertura.patient_id != paciente.id:
            raise ReservaRecusada('Este convênio não é deste paciente.')
        if (cobertura.starts_on and cobertura.starts_on > dia) or (cobertura.ends_on and cobertura.ends_on < dia):
            raise ReservaRecusada('O convênio escolhido não está vigente na data do exame.')
        return cobertura
    return None


def _conferir_tempo(recurso, inicio, duracao, encaixe, motivo):
    if not 5 <= duracao <= DURACAO_MAXIMA_MINUTOS:
        raise ReservaRecusada('A duração vai de 5 minutos a 24 horas.')
    if inicio <= timezone.now():
        raise ReservaRecusada('Não dá para marcar no passado.')
    fim = inicio + timedelta(minutes=duracao)
    motivo_fora = cabe_na_agenda(recurso, inicio, fim)
    if motivo_fora and not encaixe:
        raise ReservaRecusada(motivo_fora)
    if encaixe and not (motivo or '').strip():
        raise ReservaRecusada('Encaixe fora da agenda precisa do motivo.')
    return fim


def _gravar(reserva):
    try:
        with transaction.atomic():
            reserva.full_clean(exclude=['tenant', 'ocupacao'])
            reserva.save()
    except IntegrityError:
        raise ReservaRecusada(
            'O horário acabou de ser ocupado por outro exame nesta agenda. Escolha outro.'
        ) from None
    except ValidationError as exc:
        raise ReservaRecusada('; '.join(m for ms in exc.message_dict.values() for m in ms)) from None


@transaction.atomic
def reservar(context, user, recurso, paciente, inicio, *, duracao=None, codigo_tuss=None, descricao=None,
             solicitante=None, cobranca='', cobertura=None, observacao='', encaixe=False, motivo_encaixe=''):
    if recurso.tenant_id != context.tenant_id or paciente.tenant_id != context.tenant_id:
        raise ReservaRecusada('Agenda ou paciente de outra clínica.')
    if not recurso.ativo:
        raise ReservaRecusada('Esta agenda está desativada.')
    if solicitante is not None and solicitante.tenant_id != context.tenant_id:
        raise ReservaRecusada('Solicitante de outra clínica.')
    duracao = int(duracao or recurso.duracao_padrao)
    fim = _conferir_tempo(recurso, inicio, duracao, encaixe, motivo_encaixe)
    cobertura = _conferir_cobranca(paciente, cobranca, cobertura, timezone.localtime(inicio).date())
    reserva = Reserva(
        tenant_id=context.tenant_id, recurso=recurso, paciente=paciente, inicio=inicio, fim=fim,
        ocupacao=_ocupacao(inicio, fim, recurso.intervalo),
        codigo_tuss=(codigo_tuss if codigo_tuss is not None else recurso.codigo_tuss).strip(),
        descricao=(descricao if descricao is not None else recurso.descricao_tuss).strip()[:150],
        solicitante=solicitante, cobranca=cobranca or '', cobertura=cobertura,
        observacao=(observacao or '').strip()[:500], encaixe=bool(encaixe),
        motivo_encaixe=(motivo_encaixe or '').strip()[:255], criada_por=user,
    )
    _gravar(reserva)
    lembretes.agendar(reserva)
    record_audit_event(
        user, context.tenant_id, 'agenda_exames.reserva_criada', object_type='reserva_exame', object_id=reserva.id,
        outcome='success', integrity_metadata={
            'recurso': str(recurso.id), 'inicio': reserva.inicio.isoformat(), 'encaixe': reserva.encaixe,
        },
    )
    return reserva


def _travar(context, reserva):
    reserva = Reserva.objects.select_for_update().select_related('recurso').get(id=reserva.id)
    if reserva.tenant_id != context.tenant_id:
        raise ReservaRecusada('Exame de outra clínica.')
    return reserva


@transaction.atomic
def remarcar(context, user, reserva, inicio, *, duracao=None, encaixe=False, motivo_encaixe=''):
    reserva = _travar(context, reserva)
    if reserva.estado not in (EstadoReserva.AGENDADA, EstadoReserva.CONFIRMADA):
        raise ReservaRecusada('Só exame marcado ou confirmado pode ser remarcado.')
    duracao = int(duracao or (reserva.fim - reserva.inicio).total_seconds() // 60)
    antes = reserva.inicio
    fim = _conferir_tempo(reserva.recurso, inicio, duracao, encaixe, motivo_encaixe)
    reserva.inicio, reserva.fim = inicio, fim
    reserva.ocupacao = _ocupacao(inicio, fim, reserva.recurso.intervalo)
    reserva.estado = EstadoReserva.AGENDADA
    reserva.encaixe, reserva.motivo_encaixe = bool(encaixe), (motivo_encaixe or '').strip()[:255]
    reserva.versao_lembrete += 1
    _gravar(reserva)
    lembretes.agendar(reserva)
    record_audit_event(
        user, context.tenant_id, 'agenda_exames.reserva_remarcada', object_type='reserva_exame',
        object_id=reserva.id, outcome='success',
        integrity_metadata={'de': antes.isoformat(), 'para': inicio.isoformat()},
    )
    return reserva


@transaction.atomic
def definir_cobranca(context, user, reserva, cobranca, cobertura=None):
    """Particular ou convênio — até a realização, como no check-in da consulta."""
    reserva = _travar(context, reserva)
    if reserva.estado in (EstadoReserva.REALIZADA, EstadoReserva.CANCELADA, EstadoReserva.FALTOU):
        raise ReservaRecusada('Depois da realização, a cobrança já nasceu com a forma escolhida.')
    if cobranca not in Cobranca.values:
        raise ReservaRecusada('Forma de cobrança inválida.')
    reserva.cobertura = _conferir_cobranca(reserva.paciente, cobranca, cobertura,
                                           timezone.localtime(reserva.inicio).date())
    reserva.cobranca = cobranca
    reserva.save(update_fields=['cobranca', 'cobertura', 'updated_at'])
    record_audit_event(user, context.tenant_id, 'agenda_exames.cobranca_definida', object_type='reserva_exame',
                       object_id=reserva.id, outcome='success', integrity_metadata={'cobranca': cobranca})
    return reserva


@transaction.atomic
def mudar_estado(context, user, reserva, novo, motivo=''):
    """Confirmar, chegou, faltou, cancelar. Realizar é `realizar`."""
    reserva = _travar(context, reserva)
    if novo == EstadoReserva.REALIZADA:
        raise ReservaRecusada('Para registrar a realização, informe quem executou.')
    if novo not in TRANSICOES.get(reserva.estado, set()):
        raise ReservaRecusada(
            f'Um exame {reserva.get_estado_display().lower()} não pode passar a '
            f'{EstadoReserva(novo).label.lower()}.'
        )
    if novo == EstadoReserva.CANCELADA and not (motivo or '').strip():
        raise ReservaRecusada('Escreva o motivo do cancelamento.')
    if novo == EstadoReserva.FALTOU and reserva.inicio > timezone.now():
        raise ReservaRecusada('Falta só depois do horário do exame.')
    reserva.estado = novo
    if novo == EstadoReserva.CANCELADA:
        reserva.motivo_cancelamento = motivo.strip()[:255]
    reserva.save(update_fields=['estado', 'motivo_cancelamento', 'updated_at'])
    if novo in (EstadoReserva.CANCELADA, EstadoReserva.FALTOU):
        lembretes.cancelar_todos(reserva)
    record_audit_event(user, context.tenant_id, f'agenda_exames.reserva_{novo}', object_type='reserva_exame',
                       object_id=reserva.id, outcome='success')
    return reserva


@transaction.atomic
def realizar(context, user, reserva, executante):
    """O exame aconteceu: registra quem executou e cria a cobrança.

    Devolve `(reserva, cobranca)`; `cobranca` é `None` quando não há
    honorário para o exame — a reserva fica realizada e a tela diz o que
    cadastrar. Repetir não cria segunda cobrança.
    """
    from finance.receivables import create_receivable_for_exam

    reserva = _travar(context, reserva)
    if executante is None or executante.tenant_id != context.tenant_id:
        raise ReservaRecusada('Informe quem executou o exame (cadastro de profissionais do TISS).')
    if reserva.estado == EstadoReserva.REALIZADA:
        return reserva, create_receivable_for_exam(reserva, user.id)
    if EstadoReserva.REALIZADA not in TRANSICOES.get(reserva.estado, set()):
        raise ReservaRecusada(f'Um exame {reserva.get_estado_display().lower()} não pode ser realizado.')
    if reserva.inicio > timezone.now():
        raise ReservaRecusada('O exame ainda não começou.')
    reserva.estado = EstadoReserva.REALIZADA
    reserva.executante = executante
    reserva.realizada_em = timezone.now()
    reserva.save(update_fields=['estado', 'executante', 'realizada_em', 'updated_at'])
    lembretes.cancelar_todos(reserva)
    cobranca = create_receivable_for_exam(reserva, user.id)
    record_audit_event(user, context.tenant_id, 'agenda_exames.reserva_realizada', object_type='reserva_exame',
                       object_id=reserva.id, outcome='success',
                       integrity_metadata={'cobranca': str(cobranca.id) if cobranca else None})
    return reserva, cobranca


# ------------------------------------------------------------------ configuração

def criar_bloqueio(context, user, recurso, inicio, fim, motivo):
    if recurso.tenant_id != context.tenant_id:
        raise ReservaRecusada('Agenda de outra clínica.')
    if fim <= inicio:
        raise ReservaRecusada('O fim do bloqueio tem de ser depois do início.')
    if not (motivo or '').strip():
        raise ReservaRecusada('Escreva o motivo do bloqueio.')
    conflitos = Reserva.objects.filter(recurso=recurso, estado__in=[str(e) for e in OCUPAM],
                                       inicio__lt=fim, fim__gt=inicio).count()
    bloqueio = Bloqueio.objects.create(tenant_id=context.tenant_id, recurso=recurso, inicio=inicio, fim=fim,
                                       motivo=motivo.strip()[:255])
    record_audit_event(user, context.tenant_id, 'agenda_exames.bloqueio_criado', object_type='recurso_exame',
                       object_id=recurso.id, outcome='success', integrity_metadata={'conflitos': conflitos})
    return bloqueio, conflitos


def recursos_da_clinica(tenant_id, incluir_inativos=False):
    qs = Recurso.objects.filter(tenant_id=tenant_id).prefetch_related('janelas').order_by('nome')
    return qs if incluir_inativos else qs.filter(ativo=True)


__all__ = [
    'ReservaRecusada', 'janelas_que_cruzam', 'horarios_livres', 'reservas_do_dia', 'reservar', 'remarcar',
    'definir_cobranca', 'mudar_estado', 'realizar', 'criar_bloqueio', 'cabe_na_agenda', 'Janela',
]
