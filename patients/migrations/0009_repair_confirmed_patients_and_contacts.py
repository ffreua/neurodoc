from django.db import migrations
from django.utils import timezone


def repair_confirmed_patients_and_contacts(apps, schema_editor):
    """Repara dados gravados antes de os dois estados serem sincronizados.

    `patient_updated` só era emitido depois de um `PatientForm` válido ser
    salvo. Portanto ele é a prova auditável de que o pré-cadastro passou pela
    ficha completa, sem promover quem apenas marcou horário ou fez check-in.

    Nos pacientes já completos, os canais habilitados foram escolhas
    explícitas da mesma interface que agora registra a conferência. A data de
    migração registra o instante em que essa escolha passou a valer como
    verificação, sem inventar uma data histórica que não foi armazenada.
    """
    Patient = apps.get_model('patients', 'Patient')
    PatientContact = apps.get_model('patients', 'PatientContact')
    AuditEvent = apps.get_model('audit', 'AuditEvent')

    confirmed_ids = AuditEvent.objects.filter(
        action='patients.patient_updated',
        object_type='patient',
        outcome='success',
        object_id__isnull=False,
    ).values('object_id')
    Patient.objects.filter(
        registration_stage='preliminary', id__in=confirmed_ids,
    ).update(registration_stage='complete')

    complete_contacts = PatientContact.objects.filter(
        patient__registration_stage='complete',
    )
    repaired_at = timezone.now()
    complete_contacts.filter(
        sms_enabled=True, verified_phone_at__isnull=True,
    ).exclude(phone='').update(verified_phone_at=repaired_at)
    complete_contacts.filter(
        email_enabled=True, verified_email_at__isnull=True,
    ).exclude(email='').update(verified_email_at=repaired_at)


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0003_auditevent_imutavel'),
        ('patients', '0008_patient_photo'),
    ]

    operations = [
        migrations.RunPython(repair_confirmed_patients_and_contacts, migrations.RunPython.noop),
    ]
