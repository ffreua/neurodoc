"""Documentos dentro do atendimento, e o descarte do que nasceu sem ele (2026-11-06).

Dois defeitos achados pelo médico na mesma paciente:

1. "Documentos", no alto do atendimento, listava só o que pendia **daquele**
   atendimento. A receita emitida pela ficha (sem atendimento) ou noutra
   consulta não aparecia, e parecia não existir. Agora a lista é a do
   paciente, com os deste atendimento marcados.
2. Descartar o rascunho emitido pela ficha dava erro 500: a volta era para a
   lista do atendimento com `encounter_id=None` — e o descarte já tinha sido
   gravado, então a tela dizia "erro" sobre algo que tinha dado certo.

    docker compose exec -T app python manage.py shell < checks/check_documentos_do_atendimento.py
"""
from datetime import timedelta

from django.conf import settings as dj_settings
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from clinical.models import Encounter, EncounterKind, EncounterStatus
from documents import issuance
from documents.models import MedicalDocument, MedicalDocumentKind
from documents.pdf.prescription import SIMPLE
from patients.models import Patient, RegistrationStage
from tenancy.models import Membership, Tenant

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.get(tenant=tenant, user__email='doctor-a@demo.neurodoc.local')

cliente = Client()
cliente.force_login(medico.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()


def receita(paciente, atendimento, texto):
    return issuance.create_draft(
        tenant, paciente, atendimento, medico, medico.user_id, MedicalDocumentKind.PRESCRIPTION,
        {'prescription_text': texto, 'special_instructions': '', 'prescription_format': SIMPLE},
    )


try:
    with transaction.atomic():
        pac = Patient.objects.create(tenant=tenant, full_name='PACIENTE ROTEIRO DOCUMENTOS DO ATENDIMENTO',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        outro = Patient.objects.create(tenant=tenant, full_name='OUTRO PACIENTE ROTEIRO DOCUMENTOS',
                                       registration_stage=RegistrationStage.COMPLETE,
                                       birth_date_unknown_reason='Roteiro de verificação.')

        def consulta(paciente, dias):
            return Encounter.objects.create(
                tenant=tenant, patient=paciente, physician_membership=medico,
                occurred_at=timezone.now() - timedelta(days=dias),
                status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.FREE_TEXT, free_text='Roteiro.',
            )

        antigo, recente = consulta(pac, 30), consulta(pac, 1)
        deste = receita(pac, antigo, 'RECEITA DESTE ATENDIMENTO')
        de_outro = receita(pac, recente, 'RECEITA DE OUTRO ATENDIMENTO')
        da_ficha = receita(pac, None, 'RECEITA EMITIDA PELA FICHA')
        alheio = receita(outro, consulta(outro, 2), 'RECEITA DE OUTRO PACIENTE')

        print('1. "Documentos" do atendimento mostra os do paciente')
        r = cliente.get(reverse('documents:medical-list', args=[antigo.id]))
        html = r.content.decode()
        conferir('a lista abre', r.status_code == 200, r.status_code)
        for doc, rotulo in ((deste, 'deste atendimento'), (de_outro, 'de outro atendimento'),
                            (da_ficha, 'emitido pela ficha')):
            conferir(f'o documento {rotulo} aparece',
                     reverse('documents:medical-detail', args=[doc.id]) in html)
        conferir('o de outro paciente não aparece',
                 reverse('documents:medical-detail', args=[alheio.id]) not in html)
        conferir('o deste atendimento vem marcado', 'Este atendimento' in html)
        conferir('o da ficha vem como "Sem atendimento"', 'Sem atendimento' in html)
        conferir('o de outra consulta leva a ela', reverse('clinical:detail', args=[recente.id]) in html)

        print('2. Descartar o rascunho emitido pela ficha')
        r = cliente.post(reverse('documents:medical-discard', args=[da_ficha.id]))
        conferir('não dá erro: volta aos documentos do paciente',
                 r.status_code == 302 and r['Location'] == reverse('documents:patient-documents', args=[pac.id]),
                 f'{r.status_code} {r.get("Location")}')
        conferir('e o rascunho saiu', not MedicalDocument.objects.filter(id=da_ficha.id).exists())

        print('3. Descartar o rascunho de um atendimento continua como antes')
        r = cliente.post(reverse('documents:medical-discard', args=[deste.id]))
        conferir('volta à lista do atendimento',
                 r.status_code == 302 and r['Location'] == reverse('documents:medical-list', args=[antigo.id]),
                 f'{r.status_code} {r.get("Location")}')
        conferir('ninguém mais foi descartado',
                 MedicalDocument.objects.filter(id__in=[de_outro.id, alheio.id]).count() == 2)
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Documentos do atendimento: tudo confere.')
