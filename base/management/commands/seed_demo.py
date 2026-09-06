from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

DEMO_MARKER = 'demo-clinica'


class Command(BaseCommand):
    help = (
        'Idempotent synthetic fixtures: two demo tenants, users/memberships, '
        'patients, contacts, observations, coverage and a sample catalog release. '
        'No real e-mail/SMS is sent and no real PFX is used. Refuses to run '
        'unless NEURODOC_DEMO_ALLOWED=True (never the default in production).'
    )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.NEURODOC_DEMO_ALLOWED:
            raise CommandError('NEURODOC_DEMO_ALLOWED is False; refusing to seed demo data')

        from accounts.models import User
        from catalogs.importers import activate_release, import_catalog
        from catalogs.models import CatalogRelease
        from patients.models import (
            HealthPlan, Insurer, ObservationKind, Patient, PatientCoverage, SexAtRegistration,
        )
        from scheduling.models import Appointment, AppointmentStatus
        from tenancy.models import Membership, MembershipStatus, Role, Tenant, TenantStatus

        counts = {'tenants': 0, 'users': 0, 'memberships': 0, 'patients': 0, 'contacts': 0, 'observations': 0, 'coverages': 0}

        def get_or_create_user(email, **extra):
            user, created = User.objects.get_or_create(
                email=email, defaults={'is_active': True, **extra},
            )
            if created:
                user.set_password('DemoS3nha!123')
                user.save(update_fields=['password'])
                counts['users'] += 1
            user.email_verified_at = user.email_verified_at or timezone.now()
            user.save(update_fields=['email_verified_at'])
            return user

        def get_or_create_tenant(slug, legal_name, cnpj):
            tenant, created = Tenant.objects.get_or_create(
                slug=slug, defaults={
                    'legal_name': legal_name, 'cnpj': cnpj,
                    'status': TenantStatus.ACTIVE, 'plan': 'free',
                },
            )
            if created:
                counts['tenants'] += 1
            return tenant

        def get_or_create_membership(tenant, user, roles):
            membership, created = Membership.objects.get_or_create(
                tenant=tenant, user=user, defaults={
                    'roles': roles, 'status': MembershipStatus.ACTIVE, 'activated_at': timezone.now(),
                },
            )
            if created:
                counts['memberships'] += 1
            return membership

        def get_or_create_patient(tenant, full_name, **fields):
            patient, created = Patient.objects.get_or_create(
                tenant=tenant, full_name=full_name, defaults=fields,
            )
            if created:
                counts['patients'] += 1
            return patient

        # --- Clinica A: two doctors, one secretary, patients with full data ---
        tenant_a = get_or_create_tenant(f'{DEMO_MARKER}-a', 'Clinica Demo A Neurologia Ltda', '11444777000161')
        doctor_a = get_or_create_user('doctor-a@demo.neurodoc.local', first_name='Ana', last_name='Neuro')
        secretary_a = get_or_create_user('secretary-a@demo.neurodoc.local', first_name='Bia', last_name='Secretaria')
        get_or_create_membership(tenant_a, doctor_a, [Role.OWNER, Role.DOCTOR])
        get_or_create_membership(tenant_a, secretary_a, [Role.SECRETARY])
        membership_doctor_a = Membership.objects.get(tenant=tenant_a, user=doctor_a)

        adult = get_or_create_patient(
            tenant_a, 'Carlos Adulto da Silva', birth_date=date(1980, 5, 10),
            cpf='11144477735', sex_at_registration=SexAtRegistration.MALE,
            responsible_membership=membership_doctor_a, city='São Paulo', state='SP',
        )
        if not adult.observations.exists():
            adult.observations.create(tenant=tenant_a, kind=ObservationKind.WEIGHT, numeric_value=Decimal('82.50'), unit='kg', observed_at=timezone.now() - timedelta(days=30))
            adult.observations.create(tenant=tenant_a, kind=ObservationKind.HEIGHT, numeric_value=Decimal('1.75'), unit='m', observed_at=timezone.now() - timedelta(days=365))
            counts['observations'] += 2
        if not adult.contacts.exists():
            adult.contacts.create(
                tenant=tenant_a, name='Carlos Adulto da Silva', relationship='self',
                phone='+5511999990001', authorized_for_documents=True,
            )
            counts['contacts'] += 1

        minor = get_or_create_patient(
            tenant_a, 'Joao Menor Pereira', birth_date=date(2015, 3, 1),
            cpf=None, sex_at_registration=SexAtRegistration.MALE,
            responsible_membership=membership_doctor_a,
        )
        if not minor.contacts.exists():
            minor.contacts.create(
                tenant=tenant_a, name='Maria Pereira (mãe)', relationship='mãe',
                phone='+5511999990002', authorized_for_documents=True,
                legal_authority=True, authority_evidence='Certidão de nascimento apresentada no cadastro (demo)',
            )
            counts['contacts'] += 1

        unknown_dob = get_or_create_patient(
            tenant_a, 'Paciente Sem Data De Nascimento Conhecida',
            birth_date=None, birth_date_unknown_reason='Documentação extraviada; paciente em situação de rua',
            cpf=None,
        )

        insurer_a = Insurer.objects.get_or_create(tenant=tenant_a, name='Amil (demo)')[0]
        plan_a = HealthPlan.objects.get_or_create(tenant=tenant_a, insurer=insurer_a, name='Amil 400 (demo)')[0]
        if not PatientCoverage.objects.filter(tenant=tenant_a, patient=adult).exists():
            PatientCoverage.objects.create(
                tenant=tenant_a, patient=adult, plan=plan_a,
                member_number='DEMO-0001', starts_on=date.today() - timedelta(days=200),
            )
            counts['coverages'] += 1

        # --- Clinica B: an owner+doctor with a distinct role from the same shared user ---
        tenant_b = get_or_create_tenant(f'{DEMO_MARKER}-b', 'Clinica Demo B Neurocirurgia Ltda', '11444777000242')
        get_or_create_membership(tenant_b, doctor_a, [Role.DOCTOR])

        get_or_create_patient(
            tenant_b, 'Fernanda Exemplo Souza', birth_date=date(1992, 11, 20),
            cpf='93541134780', sex_at_registration=SexAtRegistration.FEMALE,
        )

        # --- Multiple dates: a completed visit (with a finalized encounter,
        # a return visit, a no-show, and an upcoming booking) so H-20 has
        # faltas/retornos/planos/particular to point at without relying on
        # whatever a prior manual smoke test happened to leave behind ---
        from clinical.finalization import finalize_encounter
        from clinical.models import Encounter, EncounterStatus
        from crm.services import bootstrap_default_stages
        from finance.models import PaymentCategory
        from finance.payments import record_payment
        from finance.pricing import create_fee_schedule
        from finance.receivables import create_receivable_for_encounter
        from scheduling.models import AppointmentType, AvailabilityRule
        from scheduling.services import reserve_appointment
        from tenancy.context import AccessContext
        import uuid as uuid_module

        AvailabilityRule.objects.get_or_create(
            tenant=tenant_a, physician_membership=membership_doctor_a, weekday=0,
            defaults={'local_start': timezone.datetime.min.time().replace(hour=9),
                      'local_end': timezone.datetime.min.time().replace(hour=17), 'slot_minutes': 30},
        )

        demo_ctx = AccessContext(
            user_id=doctor_a.id, tenant_id=tenant_a.id, membership_id=membership_doctor_a.id,
            permissions=frozenset(), request_id=uuid_module.uuid4(),
        )

        def _next_monday(base):
            candidate = base
            while candidate.weekday() != 0:
                candidate += timedelta(days=1)
            return candidate

        counts.setdefault('encounters', 0)
        counts.setdefault('appointments', 0)

        if not Encounter.objects.filter(tenant=tenant_a, patient=adult, status=EncounterStatus.FINALIZED).exists():
            first_visit_at = timezone.now() - timedelta(days=60)
            first_encounter = Encounter.objects.create(
                tenant=tenant_a, patient=adult, physician_membership=membership_doctor_a,
                occurred_at=first_visit_at, chief_complaint='Cefaleia recorrente há 3 meses (demo)',
                hpi='Dor pulsátil, unilateral, sem aura (demo).', plan_text='Observação e diário de crises (demo).',
            )
            finalize_encounter(demo_ctx, first_encounter, membership_doctor_a)
            return_visit_at = timezone.now() - timedelta(days=20)
            return_encounter = Encounter.objects.create(
                tenant=tenant_a, patient=adult, physician_membership=membership_doctor_a,
                occurred_at=return_visit_at, chief_complaint='Retorno — mesma queixa, melhora parcial (demo)',
                hpi='Redução de frequência das crises (demo).', plan_text='Manter conduta (demo).',
            )
            finalize_encounter(demo_ctx, return_encounter, membership_doctor_a)
            counts['encounters'] += 2

            create_fee_schedule(
                tenant_a, PaymentCategory.PRIVATE, Decimal('350.00'), Decimal('280.00'),
                date.today() - timedelta(days=400), physician=membership_doctor_a,
            )
            for encounter in [first_encounter, return_encounter]:
                receivable = create_receivable_for_encounter(encounter, doctor_a.id)
                if receivable is not None:
                    record_payment(receivable, receivable.charged_amount, 'pix', doctor_a.id)

        past_monday = _next_monday(date.today() - timedelta(days=10))
        no_show_starts_at = timezone.make_aware(timezone.datetime.combine(past_monday, timezone.datetime.min.time().replace(hour=10)))
        if not Appointment.objects.filter(tenant=tenant_a, patient=minor, starts_at=no_show_starts_at).exists():
            no_show_appt = reserve_appointment(
                demo_ctx, minor, membership_doctor_a, no_show_starts_at,
                no_show_starts_at + timedelta(minutes=30), AppointmentType.FIRST_VISIT,
            )
            no_show_appt.status = AppointmentStatus.NO_SHOW
            no_show_appt.save(update_fields=['status'])
            counts['appointments'] += 1

        future_monday = _next_monday(date.today() + timedelta(days=7))
        upcoming_starts_at = timezone.make_aware(timezone.datetime.combine(future_monday, timezone.datetime.min.time().replace(hour=11)))
        if not Appointment.objects.filter(tenant=tenant_a, patient=adult, starts_at=upcoming_starts_at).exists():
            reserve_appointment(
                demo_ctx, adult, membership_doctor_a, upcoming_starts_at,
                upcoming_starts_at + timedelta(minutes=30), AppointmentType.FOLLOW_UP,
            )
            counts['appointments'] += 1

        bootstrap_default_stages(tenant_a)

        # --- A synthetic failure: an attachment that failed the malware
        # scan, kept quarantined with a visible (synthetic) error, never
        # silently available -- exactly the failure mode H-20 asks to see
        # demonstrated without any real malicious content involved ---
        from documents.models import Attachment, AttachmentClassification, AttachmentScanStatus

        counts.setdefault('attachments', 0)
        if not Attachment.objects.filter(tenant=tenant_a, patient=adult, scan_status=AttachmentScanStatus.REJECTED).exists():
            Attachment.objects.create(
                tenant=tenant_a, patient=adult, storage_key='', original_name='exame_externo_demo.pdf',
                mime='application/pdf', bytes=1024, sha256='0' * 64,
                classification=AttachmentClassification.CLINICAL, scan_status=AttachmentScanStatus.REJECTED,
                scan_error='Falha sintética de demonstração — antivírus indisponível ao processar (demo)',
                uploaded_by=doctor_a,
            )
            counts['attachments'] += 1

        # --- Sample (non-official) catalog release, so patients app has real
        # DiagnosisCode/ProcedureCode rows to reference in later sprints ---
        sample_dir = Path(settings.BASE_DIR) / 'catalogs' / 'sample_data'
        if not CatalogRelease.objects.filter(system='CID10', version='SAMPLE-2026').exists():
            content = (sample_dir / 'cid10_sample.csv').read_text(encoding='utf-8')
            _, release = import_catalog(
                'CID10', 'SAMPLE-2026', content,
                license_note='Subconjunto sintético para desenvolvimento; não é o catálogo oficial CID-10.',
                dry_run=False,
            )
            activate_release(release)
        if not CatalogRelease.objects.filter(system='TUSS', version='SAMPLE-2026').exists():
            content = (sample_dir / 'tuss_sample.csv').read_text(encoding='utf-8')
            _, release = import_catalog(
                'TUSS', 'SAMPLE-2026', content,
                license_note='Subconjunto sintético para desenvolvimento; não é a tabela TUSS oficial.',
                dry_run=False,
            )
            activate_release(release)

        self.stdout.write(self.style.SUCCESS(f'seed_demo complete: {counts}'))
