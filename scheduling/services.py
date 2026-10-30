from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event

from .events import (
    emit_appointment_cancelled, emit_appointment_rescheduled, emit_appointment_reserved,
    invalidate_stale_reminders, schedule_reminders,
)
from .models import (
    ALLOWED_TRANSITIONS, MOTIVO_BLOQUEIO_PELA_AGENDA, Appointment, AppointmentStatus,
)


class SchedulingError(Exception):
    pass


class SlotUnavailable(SchedulingError):
    pass


class IllegalTransition(SchedulingError):
    pass


def _lock_days(physician_membership_id, dates):
    """Transaction-scoped advisory lock per (physician, day), acquired in a
    stable sorted order so multi-day appointments never deadlock against a
    concurrent reservation locking the same two days in reverse order.
    """
    for date in sorted(set(dates)):
        key = f'schedule:{physician_membership_id}:{date.isoformat()}'
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [key])


def _days_spanned(starts_at, ends_at):
    days = {starts_at.date(), ends_at.date()}
    return list(days)


def _build_occupied_range(starts_at, ends_at, buffer_minutes=0):
    from datetime import timedelta

    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    return DateTimeTZRange(
        starts_at, ends_at + timedelta(minutes=buffer_minutes), bounds='[)',
    )


@transaction.atomic
def reserve_appointment(
    context, patient, physician_membership, starts_at, ends_at, appointment_type,
    is_overbook=False, override_reason='', override_by=None, buffer_minutes=0,
):
    if is_overbook and not override_reason:
        raise SchedulingError('Encaixe exige uma justificativa.')
    _lock_days(physician_membership.id, _days_spanned(starts_at, ends_at))
    appointment = Appointment(
        tenant_id=context.tenant_id, patient=patient, physician_membership=physician_membership,
        starts_at=starts_at, ends_at=ends_at,
        occupied_range=_build_occupied_range(starts_at, ends_at, buffer_minutes),
        status=AppointmentStatus.SCHEDULED, type=appointment_type,
        is_overbook=is_overbook, override_reason=override_reason, override_by=override_by,
    )
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.appointment_reserved',
        object_type='appointment', object_id=appointment.id, outcome='success',
    )
    schedule_reminders(appointment)
    emit_appointment_reserved(appointment)
    return appointment


def _relida(appointment):
    """A consulta como está no banco, travada até o fim da transação.

    As transições gravavam a instância que a tela tinha carregado, inteira.
    Duas pessoas na mesma consulta -- uma cancela, a outra remarca --, e a
    remarcação gravava por cima o estado "agendado" da cópia velha: a
    consulta cancelada voltava à agenda, sem o motivo do cancelamento
    (auditoria de 2026-10-09, ND-1121-014). Relida sob trava, a segunda
    espera a primeira e decide sobre o que de fato ficou.
    """
    return type(appointment).objects.select_for_update().get(id=appointment.id)


#: Remarcar é mudar o quando de um horário que ainda vai acontecer.
REMARCAVEIS = (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED)


@transaction.atomic
def reschedule_appointment(context, appointment, new_starts_at, new_ends_at, actor_id, buffer_minutes=0):
    _lock_days(appointment.physician_membership_id, _days_spanned(new_starts_at, new_ends_at))
    vista_versao = appointment.row_version
    appointment = _relida(appointment)
    if appointment.status not in REMARCAVEIS:
        raise SchedulingError(
            f'Este horário está "{appointment.get_status_display().lower()}" e não pode '
            'mais ser remarcado. Recarregue a agenda.'
        )
    if appointment.row_version != vista_versao:
        raise SchedulingError(
            'Este horário mudou desde que você abriu a tela — outra pessoa pode ter '
            'remarcado ou cancelado. Recarregue antes de remarcar.'
        )
    old_starts_at, old_ends_at, old_version = appointment.starts_at, appointment.ends_at, appointment.row_version
    appointment.starts_at = new_starts_at
    appointment.ends_at = new_ends_at
    appointment.occupied_range = _build_occupied_range(new_starts_at, new_ends_at, buffer_minutes)
    appointment.row_version += 1
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        actor_id, context.tenant_id, 'scheduling.appointment_rescheduled',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'old_starts_at': old_starts_at.isoformat(), 'old_ends_at': old_ends_at.isoformat(),
            'old_row_version': old_version, 'new_row_version': appointment.row_version,
        },
    )
    schedule_reminders(appointment)
    # O paciente precisa saber que o horário dele mudou, e precisa saber
    # **hoje** -- o lembrete de 24h chegaria tarde demais para quem foi
    # remarcado para a semana que vem.
    emit_appointment_rescheduled(appointment, old_starts_at)
    return appointment


@transaction.atomic
def transition_appointment(appointment, new_status, actor_id, **extra_fields):
    appointment = _relida(appointment)
    current = AppointmentStatus(appointment.status)
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise IllegalTransition(
            f'Não é possível passar de "{current}" para "{new_status}".'
        )
    appointment.status = new_status
    appointment.row_version += 1
    for field, value in extra_fields.items():
        setattr(appointment, field, value)
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        actor_id, appointment.tenant_id, f'scheduling.appointment_{new_status}',
        object_type='appointment', object_id=appointment.id, outcome='success',
    )
    return appointment


@transaction.atomic
def cancel_appointment(appointment, actor_id, reason=''):
    result = transition_appointment(appointment, AppointmentStatus.CANCELLED, actor_id, cancellation_reason=reason)
    invalidate_stale_reminders(result)
    # Cancelar derrubava os lembretes e **não avisava ninguém**: o
    # paciente só descobria ao chegar na clínica, ou ao não receber o
    # lembrete que esperava. As duas chamadas juntas são a ordem certa --
    # primeiro cancela o que iria sair, depois manda o que tem de sair.
    emit_appointment_cancelled(result)
    return result


@transaction.atomic
def check_in(appointment, actor_id):
    appointment = transition_appointment(appointment, AppointmentStatus.CHECKED_IN, actor_id)
    from finance.receivables import create_receivable_for_appointment

    create_receivable_for_appointment(appointment, actor_id)
    return appointment


def start_appointment(appointment, actor_id):
    return transition_appointment(appointment, AppointmentStatus.IN_PROGRESS, actor_id)


def complete_appointment(appointment, actor_id):
    return transition_appointment(appointment, AppointmentStatus.COMPLETED, actor_id)


def mark_no_show(appointment, actor_id):
    if timezone.now() < appointment.ends_at:
        raise SchedulingError(
            'A falta só pode ser registrada depois do horário marcado.'
        )
    return transition_appointment(appointment, AppointmentStatus.NO_SHOW, actor_id)


# --------------------------------------------------------------------------
# Reserva a partir da grade
# --------------------------------------------------------------------------

def duration_for(physician_membership_id, appointment_type):
    """Duração configurada deste tipo para este médico, em minutos."""
    from .availability import type_durations

    return type_durations(physician_membership_id)[appointment_type]


@transaction.atomic
def reserve_from_grid(
    context, patient, physician_membership, starts_at, appointment_type,
    is_overbook=False, override_reason='', override_by=None,
):
    """Reserva a partir de um horário da grade.

    O fim é **calculado** da duração do tipo, não digitado: é o que faz uma
    primeira consulta de 80 minutos ocupar duas células de 40 sem a
    secretária ter de fazer a conta. Digitar o fim à mão era a porta de
    entrada de consulta com duração errada.

    Fora de encaixe, confere se o horário cabe na janela do médico
    (`availability.fits`). A ExclusionConstraint do banco impede
    sobreposição, mas não sabe nada sobre feriado, férias ou horário fora do
    expediente — isso é o que esta checagem cobre.
    """
    from datetime import timedelta

    from .availability import fits

    minutes = duration_for(physician_membership.id, appointment_type)
    ends_at = starts_at + timedelta(minutes=minutes)

    if not is_overbook:
        ok, reason = fits(physician_membership.id, starts_at, ends_at)
        if not ok:
            raise SlotUnavailable(reason)

    return reserve_appointment(
        context, patient, physician_membership, starts_at, ends_at, appointment_type,
        is_overbook=is_overbook, override_reason=override_reason, override_by=override_by,
    )


@transaction.atomic
def quick_register_patient(context, name, phone, note='', email='', accepts_messages=True):
    """Pré-cadastro de paciente para o agendamento por telefone.

    Grava o mínimo que a secretária tem na ligação — nome e contato — e
    marca `registration_stage='preliminary'`. O motivo de a data de
    nascimento faltar fica **escrito** no próprio cadastro em vez de o campo
    ficar vazio sem explicação: `Patient.clean()` exige data ou motivo, e a
    regra continua valendo.

    O cadastro completo é pedido no check-in, quando o paciente está na
    recepção.

    **O limite do plano vale aqui também.** Este é o segundo caminho pelo
    qual nasce paciente, e o que se esquece: a secretária cria cadastro
    marcando horário, sem nunca abrir a tela de cadastro. Deixá-lo de fora
    faria a cota valer só pela porta da frente.
    """
    from patients.contacts import SELF_RELATIONSHIP
    from patients.models import Patient, PatientContact, RegistrationStage
    from tenancy.limits import assert_can_add_patient

    assert_can_add_patient(context.tenant_id)

    patient = Patient(
        tenant_id=context.tenant_id,
        full_name=name.strip(),
        birth_date_unknown_reason='Pré-cadastro por telefone; a completar na recepção.',
        registration_stage=RegistrationStage.PRELIMINARY,
        administrative_notes=note.strip()[:2000],
    )
    patient.full_clean()
    patient.save()

    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    endereco = (email or '').strip().lower()
    if digits or endereco:
        # `sms_enabled`/`email_enabled` seguem o que a secretária marcou, e
        # não `False` fixo como antes.
        #
        # O `False` fixo contrariava o princípio que o cadastro completo
        # escreve em `patients/forms.py`: mensagem transacional é execução
        # do que a pessoa pediu, e quem deu o telefone para marcar deu para
        # ser chamado. O efeito era mudo e só aparecia depois — o
        # pré-cadastro guardava o telefone e o sistema não mandava a
        # confirmação, sem nada na tela dizendo por quê.
        #
        # Cada canal segue o próprio dado: autorizar SMS sem telefone, ou
        # e-mail sem endereço, grava um consentimento que não se exerce e
        # que depois se lê como se a pessoa tivesse recusado.
        #
        # Divulgação continua de fora: `marketing_opt_in_at` fica nulo, e é
        # ele que a LGPD (art. 11, I) exige específico e destacado.
        contact = PatientContact(
            tenant_id=context.tenant_id, patient=patient,
            # `patient.full_name`, e nao o `name` digitado: o `save()` do
            # paciente ja o gravou na forma canonica, e o contato do proprio
            # paciente guarda uma **copia** desse nome. Copiar o texto cru
            # faria a ficha e o contato nascerem divergentes -- e e o nome do
            # contato que aparece no comprovante de entrega de documento,
            # respondendo "para quem esta receita foi enviada".
            name=patient.full_name[:255], relationship=SELF_RELATIONSHIP,
            phone=digits[:16], email=endereco[:254],
            sms_enabled=bool(accepts_messages and digits),
            email_enabled=bool(accepts_messages and endereco),
            authorized_for_documents=bool(accepts_messages),
        )
        contact.full_clean()
        contact.save()

    record_audit_event(
        context.user_id, context.tenant_id, 'patients.patient_pre_registered',
        object_type='patient', object_id=patient.id, outcome='success',
    )
    return patient


@transaction.atomic
def change_appointment_patient(context, appointment, new_patient, reason, actor_id):
    """Troca o paciente de um horário marcado.

    O horário não muda; muda de quem ele é. Registra o paciente anterior no
    log, porque "quem estava marcado nesse horário" é pergunta que se faz
    depois.
    """
    appointment = _relida(appointment)
    if appointment.status not in (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED):
        raise SchedulingError(
            'Só é possível trocar o paciente de um horário agendado ou confirmado.'
        )
    previous = appointment.patient
    appointment.patient = new_patient
    appointment.row_version += 1
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        actor_id, context.tenant_id, 'scheduling.appointment_patient_changed',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'previous_patient_id': str(previous.id), 'new_patient_id': str(new_patient.id),
            'reason': reason[:255],
        },
    )
    invalidate_stale_reminders(appointment)
    schedule_reminders(appointment)
    return appointment


@transaction.atomic
def change_appointment_type(context, appointment, new_type, actor_id):
    """Troca o tipo de um horário marcado — primeira consulta, retorno...

    Pedido da recepção: a secretária marca "primeira consulta", o paciente
    liga dizendo que já veio antes, e o único caminho era cancelar e marcar
    de novo, perdendo o horário para quem estivesse olhando a agenda.

    **Só antes do check-in.** O tipo decide o preço: é com ele que
    `finance.receivables` escolhe a linha da tabela de honorários, e a
    cobrança nasce no check-in. Trocar depois deixaria a cobrança com o
    preço de um tipo e o agendamento dizendo outro. Depois do check-in, o
    lugar de corrigir é o financeiro, com ajuste e motivo.

    **A duração acompanha o tipo; o início não muda.** Até 2026-10-13 a
    troca deixava o horário intacto, com o argumento de que encolher
    "liberaria uma sobra que ninguém pediu". Pediram: a primeira consulta
    das 17h (80 min) trocada para retorno (40 min) continuava ocupando até
    18h20, e o horário das 17h40 não voltava a ficar livre. A duração é do
    tipo em toda outra porta (`reserve_from_grid`); só aqui ela ficava
    presa ao tipo anterior.

    - **encolher** sempre cabe, e as células do fim voltam a ficar livres;
    - **esticar** passa pela mesma conferência de quem marca
      (`availability.fits`, ignorando a própria consulta): se o tempo a
      mais invade outro paciente, um bloqueio ou o fim do expediente, a
      troca é recusada inteira, dizendo por quê, e nada muda — o caminho
      é remarcar para onde caiba;
    - **encaixe** não passa pela grade, como não passou ao ser marcado.

    O intervalo pós-consulta (`buffer_minutes`) que a reserva tiver é
    preservado: ele é medido do fim, e o fim é o que muda.
    """
    from datetime import timedelta

    from django.db import IntegrityError

    from .availability import fits
    from .models import AppointmentType

    appointment = _relida(appointment)
    if appointment.status not in (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED):
        raise SchedulingError(
            'Só é possível trocar o tipo de um horário agendado ou confirmado. '
            'Depois da chegada, o tipo já definiu a cobrança.'
        )
    if new_type not in AppointmentType.values:
        raise SchedulingError('Tipo de atendimento inválido.')
    previous = appointment.type
    if previous == new_type:
        return appointment

    old_ends_at = appointment.ends_at
    new_ends_at = appointment.starts_at + timedelta(
        minutes=duration_for(appointment.physician_membership_id, new_type),
    )
    rotulo = AppointmentType(new_type).label
    if new_ends_at > old_ends_at and not appointment.is_overbook:
        _lock_days(
            appointment.physician_membership_id,
            _days_spanned(appointment.starts_at, new_ends_at),
        )
        ok, reason = fits(
            appointment.physician_membership_id, appointment.starts_at, new_ends_at,
            ignorar=appointment.id,
        )
        if not ok:
            raise SlotUnavailable(
                f'Não foi possível trocar para {rotulo}: {reason} '
                'Para manter o novo tipo, remarque para um horário em que ele caiba.'
            )

    upper = getattr(appointment.occupied_range, 'upper', None)
    buffer_minutes = int((upper - old_ends_at).total_seconds() // 60) if upper else 0
    appointment.type = new_type
    appointment.ends_at = new_ends_at
    appointment.occupied_range = _build_occupied_range(
        appointment.starts_at, new_ends_at, max(buffer_minutes, 0),
    )
    appointment.row_version += 1
    appointment.full_clean()
    try:
        with transaction.atomic():
            appointment.save()
    except IntegrityError:
        # A ExclusionConstraint pegou quem marcou no tempo a mais entre a
        # conferência e a gravação.
        raise SlotUnavailable(
            f'Não foi possível trocar para {rotulo}: o horário seguinte acabou de ser '
            'ocupado por outra reserva.'
        )
    record_audit_event(
        actor_id, context.tenant_id, 'scheduling.appointment_type_changed',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'previous_type': previous, 'new_type': new_type,
            'old_ends_at': old_ends_at.isoformat(), 'new_ends_at': new_ends_at.isoformat(),
        },
    )
    return appointment


def billing_options(appointment):
    """As coberturas do paciente para o painel "Forma de cobrança" do modal.

    Só o que a recepção já vê na ficha (convênio, plano, carteira mascarada
    e vigência) — nada clínico. Vigência medida no dia do atendimento.
    """
    dia = timezone.localtime(appointment.starts_at).date()
    opcoes = []
    for cobertura in (appointment.patient.coverages
                      .select_related('plan__insurer').order_by('-starts_on', '-created_at')):
        vigente = not ((cobertura.starts_on and cobertura.starts_on > dia)
                       or (cobertura.ends_on and cobertura.ends_on < dia))
        carteira = cobertura.member_number or ''
        opcoes.append({
            'id': str(cobertura.id),
            'rotulo': f'{cobertura.plan.insurer.name} — {cobertura.plan.name}'
                      + (f' · carteira final {carteira[-4:]}' if carteira else ''),
            'vigente': vigente,
            'ativa_na_ficha': cobertura.id == appointment.patient.active_coverage_id,
        })
    return opcoes


@transaction.atomic
def set_billing_mode(context, appointment, mode, coverage_id, actor_id):
    """Particular ou convênio, **neste** atendimento (1.30).

    Só antes do check-in, pela mesma razão do tipo de consulta: a cobrança
    nasce na chegada, com o preço da forma escolhida (`finance.receivables
    ._price_for`). Depois disso, quem corrige é o financeiro, com ajuste e
    motivo — trocar aqui deixaria a cobrança dizendo uma coisa e o
    agendamento outra.

    `mode` vazio volta ao "não informado", em que vale a regra antiga
    (cobertura vigente na ficha = convênio). Não mexe em `row_version`: a
    forma de cobrança não muda o horário, e mudar a versão invalidaria os
    lembretes já agendados (`scheduling.events`).
    """
    from patients.models import PatientCoverage

    from .models import BillingMode

    appointment = _relida(appointment)
    if appointment.status not in (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED):
        raise SchedulingError(
            'A forma de cobrança só muda antes da chegada. Depois do check-in, '
            'corrija pelo financeiro.'
        )
    mode = mode or ''
    if mode not in ('', *BillingMode.values):
        raise SchedulingError('Forma de cobrança inválida.')
    cobertura = None
    if mode == BillingMode.INSURANCE:
        cobertura = PatientCoverage.objects.filter(
            id=coverage_id, tenant_id=context.tenant_id, patient_id=appointment.patient_id,
        ).first() if coverage_id else None
        if cobertura is None:
            raise SchedulingError('Escolha um convênio deste paciente.')
    anterior = {'mode': appointment.billing_mode, 'coverage': str(appointment.coverage_id or '')}
    appointment.billing_mode = mode
    appointment.coverage = cobertura
    appointment.full_clean()
    appointment.save(update_fields=['billing_mode', 'coverage', 'updated_at'])
    record_audit_event(
        actor_id, context.tenant_id, 'scheduling.appointment_billing_changed',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'from': anterior,
            'to': {'mode': mode, 'coverage': str(cobertura.id) if cobertura else ''},
        },
    )
    return appointment


@transaction.atomic
def include_extra_hours(context, physician_membership, day, start_time, cells, reason=''):
    """Abre horário extra num dia, a partir da própria agenda.

    O atendimento extra já existia (`ScheduleBlockKind.EXTRA_AVAILABILITY`),
    mas só em Configurar horários, com início e fim digitados como data e
    hora. A secretária que ouve "o doutor vai ficar até mais tarde na
    quinta" está olhando a agenda, não a configuração.

    Pede **quantos horários**, e não o fim: o fim é calculado da célula do
    dia. Um fim digitado à mão que não fechasse a célula abria uma janela
    em que nenhuma consulta cabe — o extra seria gravado e não apareceria
    na grade, e a secretária concluiria que o botão não funciona.

    **Horário excluído pelo modal de marcar é reaberto**, e não recusado:
    excluir e incluir de novo no mesmo lugar é desfazer. O pedaço do
    período que estava excluído volta (o `REMOVED_SLOT` é apagado ou
    aparado), e só o que fica fora de toda janela vira atendimento extra
    novo. Devolve esse extra, ou `None` quando só houve reabertura.

    Recusa, dizendo por quê, o que viraria grade torta ou letra morta:

    - horário que já é de atendimento e **não** foi excluído (a cadência
      seria dupla, e as células se sobreporiam);
    - horário sob bloqueio de data (férias, feriado): o bloqueio vence o
      extra em `open_intervals`, e o extra não abriria nada;
    - o que já passou, e o que atravessa a meia-noite.
    """
    from datetime import timedelta

    from .availability import (
        _combine, _subtract, blocks_on, breaks_on, day_bounds, rules_on, slot_minutes_for,
        suggested_slot_minutes,
    )
    from .models import ScheduleBlockKind

    if not 1 <= cells <= 24:
        raise SchedulingError('Informe de 1 a 24 horários.')
    rules = rules_on(physician_membership.id, day)
    step = (
        slot_minutes_for(physician_membership.id, day, rules=rules)
        or suggested_slot_minutes(physician_membership.id)
    )
    inicio = _combine(day, start_time)
    fim = inicio + timedelta(minutes=step * cells)
    if fim > day_bounds(day)[1]:
        raise SchedulingError('O horário extra precisa terminar no mesmo dia.')
    if inicio < timezone.now():
        raise SchedulingError('Não dá para incluir horário que já passou.')

    _lock_days(physician_membership.id, [day])
    blocks = blocks_on(physician_membership.id, day)
    declarado = [(_combine(day, r.local_start), _combine(day, r.local_end)) for r in rules]
    for pausa in breaks_on(physician_membership.id, day):
        declarado = _subtract(
            declarado, _combine(day, pausa.local_start), _combine(day, pausa.local_end),
        )
    declarado += [
        (b.start_at, b.end_at) for b in blocks if b.kind == ScheduleBlockKind.EXTRA_AVAILABILITY
    ]

    def _hhmm(valor):
        return timezone.localtime(valor).strftime('%H:%M')

    removidos = [
        b for b in blocks
        if b.kind == ScheduleBlockKind.REMOVED_SLOT and b.start_at < fim and inicio < b.end_at
    ]
    # O que já é atendimento **e está valendo**: a janela declarada dentro
    # do pedido, menos o que foi excluído (e que agora será reaberto).
    vigente = [(max(c, inicio), min(t, fim)) for c, t in declarado if c < fim and inicio < t]
    for b in removidos:
        vigente = _subtract(vigente, b.start_at, b.end_at)
    if vigente:
        comeco, termino = min(vigente)
        raise SchedulingError(
            f'Das {_hhmm(comeco)} às {_hhmm(termino)} já é horário de atendimento '
            'neste dia. Escolha um início fora desse período.'
        )
    for b in blocks:
        if (b.kind not in (ScheduleBlockKind.EXTRA_AVAILABILITY, ScheduleBlockKind.REMOVED_SLOT)
                and b.start_at < fim and inicio < b.end_at):
            raise SchedulingError(
                f'Este horário está bloqueado na agenda ({b.reason or b.get_kind_display()}). '
                'Remova o bloqueio em Configurar horários antes de abrir horário nele.'
            )

    for b in removidos:
        sobra = _subtract([(b.start_at, b.end_at)], inicio, fim)
        reaberto = (max(b.start_at, inicio), min(b.end_at, fim))
        if sobra:
            # O excluído passava do período pedido: reabre só o que foi pedido.
            b.start_at, b.end_at = sobra[0]
            b.save(update_fields=['start_at', 'end_at'])
            for comeco, termino in sobra[1:]:
                create_block(
                    context, physician_membership, ScheduleBlockKind.REMOVED_SLOT,
                    comeco, termino, reason=b.reason,
                )
        else:
            b.delete()
        record_audit_event(
            context.user_id, context.tenant_id, 'scheduling.slot_reopened',
            object_type='membership', object_id=physician_membership.id, outcome='success',
            integrity_metadata={'start': reaberto[0].isoformat(), 'end': reaberto[1].isoformat()},
        )

    novo = [(inicio, fim)]
    for comeco, termino in declarado:
        novo = _subtract(novo, comeco, termino)
    extra = None
    for comeco, termino in novo:
        extra = create_block(
            context, physician_membership, ScheduleBlockKind.EXTRA_AVAILABILITY, comeco, termino,
            reason=reason or 'Horário incluído pela agenda',
        )
    return extra


@transaction.atomic
def remove_free_slot(context, physician_membership, starts_at):
    """Exclui um horário livre, a partir do próprio modal de marcar.

    É o avesso de `include_extra_hours`, e pela mesma razão: a secretária
    que ouve "na terça às 15h eu não atendo" está olhando a agenda, e
    Configurar horários pedia início e fim digitados para fechar uma
    célula só.

    **Só fecha o que está livre agora**, conferido na grade montada dentro
    da trava do dia — a mesma de `reserve_from_grid`. Sem a trava, duas
    secretárias (uma marcando, outra excluindo) poderiam gravar as duas
    coisas, e o paciente ficaria marcado num horário que a agenda diz não
    existir. A grade responde de uma vez pelo passado, pelo ocupado, pelo
    já bloqueado e pelo que nunca foi horário.

    Duas formas de fechar, e a escolha é para a grade não mentir:

    - a célula que **é** um atendimento extra inteiro (o horário incluído
      pela agenda, de uma célula) tem o extra apagado: incluir e excluir é
      desfazer, e um bloqueio por cima deixaria na tela uma célula fechada
      num horário em que o médico nunca atendeu;
    - qualquer outra vira `ScheduleBlock` de horário excluído
      (`REMOVED_SLOT`), do tamanho da célula. Ela **some** da grade, e
      volta com Incluir horário no mesmo lugar. Apagar a regra semanal
      não serve: ela vale para todas as terças.

    Na 1.14 a segunda forma era um bloqueio comum, que a grade desenhava
    "fechado" -- e que fazia Incluir horário recusar o lugar como "já é
    horário de atendimento". Quem exclui quer que o horário suma e
    possa voltar.
    """
    from .availability import blocks_on, day_grid
    from .models import ScheduleBlockKind

    day = timezone.localtime(starts_at).date()
    _lock_days(physician_membership.id, [day])

    cell = next(
        (c for c in day_grid(physician_membership.id, day) if c['start'] == starts_at), None,
    )
    if cell is None or cell['status'] != 'free':
        raise SlotUnavailable(
            'Este horário não está mais livre — foi marcado, bloqueado ou já passou. '
            'A agenda foi atualizada.'
        )

    extra = next(
        (b for b in blocks_on(physician_membership.id, day)
         if b.kind == ScheduleBlockKind.EXTRA_AVAILABILITY
         and b.start_at == cell['start'] and b.end_at == cell['end']),
        None,
    )
    if extra is not None:
        extra_id = extra.id
        extra.delete()
        record_audit_event(
            context.user_id, context.tenant_id, 'scheduling.block_deleted',
            object_type='membership', object_id=physician_membership.id, outcome='success',
            integrity_metadata={
                'block_id': str(extra_id), 'kind': ScheduleBlockKind.EXTRA_AVAILABILITY,
                'start': cell['start'].isoformat(), 'end': cell['end'].isoformat(),
                'origem': 'excluir_horario',
            },
        )
        # O extra pode ter sido gravado sobre a janela semanal por
        # Configurar horários, que não recusa isso. Apagá-lo então não
        # fecha nada, e a célula continuaria livre.
        still_free = any(
            c['start'] == starts_at and c['status'] == 'free'
            for c in day_grid(physician_membership.id, day)
        )
        if not still_free:
            return None

    return create_block(
        context, physician_membership, ScheduleBlockKind.REMOVED_SLOT, cell['start'], cell['end'],
        reason='Horário excluído pela agenda',
    )


@transaction.atomic
def block_free_slot(context, physician_membership, starts_at):
    """Bloqueia um horário livre, a partir do próprio modal de marcar.

    Irmão de `remove_free_slot`, e a diferença entre os dois é a
    estatística: **bloqueado** é horário que existia e não foi oferecido
    (o médico vai a um congresso, a sala está em reforma), e entra na
    conta dos bloqueados do mês; **excluído** é horário que deixou de
    existir, e não entra em conta nenhuma. Pedido do Dr. Fernando ao
    testar a 1.14.1: com só o Excluir, a estatística perdia o horário que
    ele quis fechar sem tirar da agenda.

    A célula continua desenhada, "bloqueada", e se desfaz com um clique
    nela (`unblock_slot`). Mesma trava e mesma conferência na grade de
    `remove_free_slot`: só fecha o que está livre agora.
    """
    from .availability import day_grid
    from .models import ScheduleBlockKind

    day = timezone.localtime(starts_at).date()
    _lock_days(physician_membership.id, [day])
    cell = next(
        (c for c in day_grid(physician_membership.id, day) if c['start'] == starts_at), None,
    )
    if cell is None or cell['status'] != 'free':
        raise SlotUnavailable(
            'Este horário não está mais livre — foi marcado, bloqueado ou já passou. '
            'A agenda foi atualizada.'
        )
    return create_block(
        context, physician_membership, ScheduleBlockKind.BLOCK, cell['start'], cell['end'],
        reason=MOTIVO_BLOQUEIO_PELA_AGENDA,
    )


@transaction.atomic
def unblock_slot(context, physician_membership, block_id):
    """Desfaz o bloqueio feito por `block_free_slot`, com um clique na célula.

    Só o que aquele botão gravou (tipo e motivo), e só o que ainda não
    passou: desbloquear um horário de ontem mudaria a estatística de um
    dia encerrado sem devolver vaga nenhuma.
    """
    from .models import ScheduleBlock, ScheduleBlockKind

    block = (
        ScheduleBlock.objects.select_for_update()
        .filter(
            id=block_id, tenant_id=context.tenant_id, physician_membership=physician_membership,
            kind=ScheduleBlockKind.BLOCK, reason=MOTIVO_BLOQUEIO_PELA_AGENDA,
        )
        .first()
    )
    if block is None:
        raise SchedulingError(
            'Este bloqueio não existe mais, ou foi feito em Configurar horários — '
            'remova-o por lá.'
        )
    if block.end_at <= timezone.now():
        raise SchedulingError('Este horário já passou; o bloqueio fica como registro do dia.')
    inicio, fim = block.start_at, block.end_at
    block.delete()
    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.block_deleted',
        object_type='membership', object_id=physician_membership.id, outcome='success',
        integrity_metadata={
            'block_id': str(block_id), 'kind': ScheduleBlockKind.BLOCK,
            'start': inicio.isoformat(), 'end': fim.isoformat(), 'origem': 'desbloquear_horario',
        },
    )
    return inicio


@transaction.atomic
def create_block(context, physician_membership, kind, start_at, end_at, reason=''):
    from .models import ScheduleBlock

    block = ScheduleBlock(
        tenant_id=context.tenant_id, physician_membership=physician_membership,
        start_at=start_at, end_at=end_at, kind=kind, reason=reason[:255], override_rule=True,
    )
    block.full_clean()
    block.save()
    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.block_created',
        object_type='membership', object_id=physician_membership.id, outcome='success',
        integrity_metadata={'kind': kind, 'start': start_at.isoformat(), 'end': end_at.isoformat()},
    )
    return block
