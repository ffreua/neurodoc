from django.db import migrations
from django.utils import timezone


def backfill_checkins(apps, schema_editor):
    """Liga pares inequívocos e cobra check-ins já realizados, sem duplicar.

    Esta migration é deliberadamente não atômica. A alteração estrutural foi
    concluída em 0004 antes de o serviço de cobrança usar a conexão normal da
    aplicação; assim ele nunca espera por um lock DDL mantido pela própria
    conexão de migrations.
    """
    alias = schema_editor.connection.alias
    AppointmentState = apps.get_model('scheduling', 'Appointment')
    EncounterState = apps.get_model('clinical', 'Encounter')
    ReceivableState = apps.get_model('finance', 'Receivable')

    appointment_ids = AppointmentState.objects.using(alias).filter(
        status__in=['checked_in', 'in_progress', 'completed'],
    ).values_list('id', flat=True)

    # Instalacao nova nao tem check-in para preencher -- e precisa sair aqui,
    # ANTES do bloco final, que usa os modelos da aplicacao.
    #
    # Por que isto existe. Aquele bloco faz `select_related('patient')` com o
    # `Patient` de HOJE, entao o SELECT pede todas as colunas atuais --
    # inclusive `legacy_id`, que so e criada por uma migration de `patients`
    # posterior a esta. Num banco que foi crescendo migration a migration a
    # coluna ja esta la e nada acontece; num banco **do zero** a cadeia para
    # aqui com `column patients_patient.legacy_id does not exist`, e a
    # instalacao limpa fica impossivel.
    #
    # Ninguem viu porque producao e os ambientes de desenvolvimento nasceram
    # antes desta migration e foram migrando aos poucos. So aparece em quem
    # instala agora -- e descobre no primeiro comando.
    #
    # A guarda e por dado, e nao por versao: se nao ha agendamento nenhum,
    # nao ha o que preencher, e pular e o resultado certo de qualquer forma.
    if not appointment_ids.exists():
        return

    for appointment_id in appointment_ids.iterator():
        appointment = AppointmentState.objects.using(alias).get(id=appointment_id)
        candidates = EncounterState.objects.using(alias).filter(
            tenant_id=appointment.tenant_id,
            patient_id=appointment.patient_id,
            physician_membership_id=appointment.physician_membership_id,
            appointment_id__isnull=True,
            occurred_at__date=timezone.localtime(appointment.starts_at).date(),
        )
        if candidates.count() == 1:
            encounter = candidates.first()
            EncounterState.objects.using(alias).filter(id=encounter.id).update(
                appointment_id=appointment.id,
            )
        else:
            encounter = EncounterState.objects.using(alias).filter(
                appointment_id=appointment.id,
            ).first()
        if encounter is not None:
            ReceivableState.objects.using(alias).filter(
                tenant_id=appointment.tenant_id,
                encounter_id=encounter.id,
                appointment_id__isnull=True,
            ).update(appointment_id=appointment.id)

    # O schema já foi confirmado por 0004. Agora é seguro reaproveitar a
    # resolução de preços do fluxo online pela conexão normal da aplicação.
    from finance.receivables import create_receivable_for_appointment
    from scheduling.models import Appointment

    for appointment in Appointment.objects.filter(
        status__in=['checked_in', 'in_progress', 'completed'],
    ).select_related('tenant', 'patient', 'physician_membership').iterator():
        create_receivable_for_appointment(appointment, actor_id=None)


def reverse_backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Receivable = apps.get_model('finance', 'Receivable')
    appointment_only = Receivable.objects.using(alias).filter(encounter_id__isnull=True)
    if appointment_only.filter(payments__isnull=False).exists():
        raise RuntimeError('Não é seguro reverter: há pagamento em cobrança originada no check-in.')
    appointment_only.delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('finance', '0004_cobranca_no_checkin'),
    ]

    operations = [
        migrations.RunPython(backfill_checkins, reverse_backfill, atomic=False),
    ]
