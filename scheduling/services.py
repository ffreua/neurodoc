from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event

from .events import emit_appointment_reserved, invalidate_stale_reminders, schedule_reminders
from .models import ALLOWED_TRANSITIONS, Appointment, AppointmentStatus


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
        raise SchedulingError('Overbook requires a justification')
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


@transaction.atomic
def reschedule_appointment(context, appointment, new_starts_at, new_ends_at, actor_id, buffer_minutes=0):
    _lock_days(appointment.physician_membership_id, _days_spanned(new_starts_at, new_ends_at))
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
    return appointment


@transaction.atomic
def transition_appointment(appointment, new_status, actor_id, **extra_fields):
    current = AppointmentStatus(appointment.status)
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise IllegalTransition(f'{current} -> {new_status} is not allowed')
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


def cancel_appointment(appointment, actor_id, reason=''):
    result = transition_appointment(appointment, AppointmentStatus.CANCELLED, actor_id, cancellation_reason=reason)
    invalidate_stale_reminders(result)
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
        raise SchedulingError('Cannot mark no-show before the appointment window ends')
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
            name=name.strip()[:255], relationship=SELF_RELATIONSHIP,
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
