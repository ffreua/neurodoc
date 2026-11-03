"""O que é do autor e o que é da conta (revisão de 2026-11-02).

Duas fronteiras que a revisão achou abertas:

1. **Emitir em papel e refazer como impressa são do autor.** Revisar,
   descartar e retificar já conferiam quem escreveu o documento; estas duas
   rotas aceitavam qualquer médico da clínica, que numerava em papel — com o
   nome e o CRM de outro — o rascunho alheio.
2. **Registro profissional e segundo fator são da conta, não do vínculo.**
   Validar o CRM libera assinar e emitir em **toda** organização da pessoa,
   e redefinir o segundo fator derruba as sessões de todas. A tela de uma
   clínica só mexe nisso para quem atende só nela.

    docker compose exec -T app python manage.py shell < checks/check_autoria_e_conta.py
"""
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.db import transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import PhysicianProfile, User
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from documents.pdf.prescription import SIMPLE
from patients.models import Patient
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(rotulo)


def cliente(vinculo):
    c = Client()
    c.force_login(vinculo.user)
    s = c.session
    s['tenant_id'] = str(vinculo.tenant_id)
    s.save()
    return c


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.get(slug='demo-clinica-b')
autor = Membership.objects.get(user__email='doctor-a@demo.neurodoc.local', tenant=clinica)
dono_a = Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE,
                                   roles__contains=[Role.OWNER]).order_by('created_at').first()
dono_b = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE,
                                   roles__contains=[Role.OWNER]).order_by('created_at').first()
paciente = Patient.objects.filter(tenant=clinica).order_by('created_at').first()

try:
    with transaction.atomic():
        print('=== 1. Emitir em papel e refazer como impressa: só o autor ===')
        colega_user = User.objects.create_user(email='colega-roteiro@example.invalid', password=None,
                                               email_verified_at=timezone.now())
        colega = Membership.objects.create(tenant=clinica, user=colega_user, roles=[Role.DOCTOR],
                                           status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        doc = issuance.create_draft(
            clinica, paciente, None, autor, autor.user_id, MedicalDocumentKind.PRESCRIPTION,
            {'prescription_text': 'Dipirona 500mg, 1 comprimido de 6/6h se dor',
             'special_instructions': '', 'prescription_format': SIMPLE},
        )
        r = cliente(colega).post(f'/app/documents/medical/{doc.id}/emitir-em-papel/')
        doc.refresh_from_db()
        conferir('outro médico não emite em papel o rascunho alheio',
                 # 403 pela autoria, ou 404 se o colega ainda nem tem o CRM validado
                 # (desde a revisão, S2-b, emitir em papel exige `ISSUE_DOCUMENT`).
                 r.status_code in (403, 404) and doc.status == MedicalDocumentStatus.DRAFT and not doc.document_number,
                 f'{r.status_code} {doc.status}')
        r = cliente(colega).post(f'/app/documents/medical/{doc.id}/refazer-impressa/')
        conferir('nem o refaz como impressa', r.status_code in (403, 404)
                 and MedicalDocument.objects.get(id=doc.id).status == MedicalDocumentStatus.DRAFT)
        r = cliente(autor).post(f'/app/documents/medical/{doc.id}/emitir-em-papel/')
        doc.refresh_from_db()
        conferir('o autor emite', r.status_code == 302 and doc.status == MedicalDocumentStatus.ISSUED_ON_PAPER
                 and bool(doc.document_number), f'{r.status_code} {doc.status}')

        print('=== 2. Registro e segundo fator de quem atende em duas organizações ===')
        dupla_user = User.objects.create_user(email='dupla-roteiro@example.invalid', password=None,
                                              email_verified_at=timezone.now())
        Membership.objects.create(tenant=clinica, user=dupla_user, roles=[Role.DOCTOR],
                                  status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        dupla_b = Membership.objects.create(tenant=outra, user=dupla_user, roles=[Role.DOCTOR],
                                            status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        perfil = PhysicianProfile.objects.create(
            user=dupla_user, crm_number='77001', crm_state='SP', professional_name='DRA DUPLA',
            verification_status=PhysicianProfile.VerificationStatus.REJECTED,
        )
        TOTPDevice.objects.create(user=dupla_user, name='roteiro', confirmed=True)
        b = cliente(dono_b)
        b.post(f'/app/org/equipe/{dupla_b.id}/registro-profissional/validar/')
        perfil.refresh_from_db()
        conferir('a outra clínica não valida o CRM que vale também aqui',
                 perfil.verification_status == PhysicianProfile.VerificationStatus.REJECTED)
        b.post(f'/app/org/equipe/{dupla_b.id}/registro-profissional/', {
            'crm_number': '77001', 'crm_state': 'SP', 'professional_name': 'NOME TROCADO', 'rqe': '',
        })
        perfil.refresh_from_db()
        conferir('nem troca o nome profissional', perfil.professional_name == 'DRA DUPLA')
        b.post(f'/app/org/equipe/{dupla_b.id}/resetar-mfa/', {'code': '000000'})
        conferir('nem redefine o segundo fator', TOTPDevice.objects.filter(user=dupla_user).exists())

        print('=== 3. Quem atende só nesta clínica continua como antes ===')
        so_user = User.objects.create_user(email='so-roteiro@example.invalid', password=None,
                                           email_verified_at=timezone.now())
        so_b = Membership.objects.create(tenant=outra, user=so_user, roles=[Role.DOCTOR],
                                         status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        PhysicianProfile.objects.create(user=so_user, crm_number='77002', crm_state='SP',
                                        professional_name='DR SO')
        b.post(f'/app/org/equipe/{so_b.id}/registro-profissional/validar/')
        conferir('a clínica valida o CRM de quem atende só nela',
                 PhysicianProfile.objects.get(user=so_user).verification_status
                 == PhysicianProfile.VerificationStatus.VERIFIED)
        # O mesmo POST da seção 2: aqui ele grava — prova que a recusa de lá
        # vem da regra, e não de um formulário mal preenchido.
        b.post(f'/app/org/equipe/{so_b.id}/registro-profissional/', {
            'crm_number': '77002', 'crm_state': 'SP', 'professional_name': 'NOME TROCADO', 'rqe': '',
        })
        conferir('e troca o nome profissional dele',
                 PhysicianProfile.objects.get(user=so_user).professional_name == 'NOME TROCADO')
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Autoria e conta: tudo confere.')
