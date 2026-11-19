"""A ordem dos resultados de exame e das medicações no prontuário.

Tenta quebrar. As perguntas são:

- na aba de exames do atendimento, o mais recente fica em cima e o mais
  antigo embaixo, medido pela **posição** no HTML -- inclusive com um exame
  **sem data**, que na ordem decrescente do PostgreSQL subia ao topo?
- dois exames no mesmo dia: o registrado por último em cima?
- nas medicações, as em uso juntas, depois as suspensas, depois as
  concluídas, e dentro de cada grupo por nome -- mesmo com os nomes
  intercalados de propósito?
- o resumo do atendimento e o resumo de todos os atendimentos seguem a
  mesma ordem?
- a gaveta da consulta anterior também?
- a IA, que lê só os N mais recentes, não perde o mais recente para o
  exame sem data?
- o acervo usa a mesma ordem?
"""
import datetime
from types import SimpleNamespace

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from accounts.models import User
from ai.tools.clinical import get_exam_results
from clinical.models import (
    Encounter, EncounterStatus, ExamResult, Medication, MedicationStatus,
)
from clinical.ordem import chave_da_medicacao, chave_do_exame
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def confere(cond, rotulo):
    print(f'  {"ok   " if cond else "FALHA"} {rotulo}')
    if not cond:
        falhas.append(rotulo)


def em_ordem(corpo, nomes, rotulo):
    posicoes = [corpo.find(n) for n in nomes]
    presentes = all(p >= 0 for p in posicoes)
    confere(presentes and posicoes == sorted(posicoes),
            f'{rotulo}: {" > ".join(nomes)} (posições {posicoes})')


clinica = Tenant.objects.get(slug='demo-clinica-a')
email_medico = 'doctor-a@demo.neurodoc.local'
medico = Membership.objects.get(tenant=clinica, user__email=email_medico, status=MembershipStatus.ACTIVE)

doc = Client()
doc.force_login(User.objects.get(email=email_medico))
sessao = doc.session
sessao['tenant_id'] = str(clinica.id)
sessao.save()

paciente = Patient.objects.create(
    tenant=clinica, full_name='PACIENTE DO ROTEIRO DE ORDEM',
    registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
    birth_date_unknown_reason='Roteiro de verificacao.',
)
encontros = []

# Nomes com marca única: a busca pela posição não pode casar com texto da tela.
EX_SEM_DATA = 'EXAMEORD-SEMDATA'
EX_NOV = 'EXAMEORD-NOVEMBRO'
EX_OUT_TARDE = 'EXAMEORD-OUTUBRO-REGISTRADO-DEPOIS'
EX_OUT_CEDO = 'EXAMEORD-OUTUBRO-REGISTRADO-ANTES'
EX_SET = 'EXAMEORD-SETEMBRO'

try:
    anterior = Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico,
        occurred_at=timezone.now() - datetime.timedelta(days=30),
    )
    encontros.append(anterior.id)
    enc = Encounter.objects.create(
        tenant=clinica, patient=paciente, physician_membership=medico, occurred_at=timezone.now(),
    )
    encontros.append(enc.id)

    def exame(nome, dia, quando_registrado):
        e = ExamResult.objects.create(
            tenant=clinica, encounter=enc, patient=paciente, name=nome, performed_on=dia,
            report_text=f'laudo {nome}',
        )
        ExamResult.objects.filter(id=e.id).update(created_at=quando_registrado)
        return e

    agora = timezone.now()
    # Criados fora de ordem de propósito: a ordem de inserção não pode decidir.
    exame(EX_SET, datetime.date(2026, 9, 3), agora - datetime.timedelta(hours=5))
    exame(EX_SEM_DATA, None, agora)
    exame(EX_OUT_CEDO, datetime.date(2026, 10, 20), agora - datetime.timedelta(hours=4))
    exame(EX_NOV, datetime.date(2026, 11, 2), agora - datetime.timedelta(hours=6))
    exame(EX_OUT_TARDE, datetime.date(2026, 10, 20), agora - datetime.timedelta(hours=1))
    ordem_exames = [EX_NOV, EX_OUT_TARDE, EX_OUT_CEDO, EX_SET, EX_SEM_DATA]

    def remedio(encontro, nome, situacao):
        return Medication.objects.create(tenant=clinica, encounter=encontro, name=nome, status=situacao)

    # Nomes intercalados: na ordem só por nome, suspensa e concluída ficariam no meio.
    for e in (enc, anterior):
        remedio(e, 'MEDORD-B-SUSPENSA', MedicationStatus.SUSPENDED)
        remedio(e, 'MEDORD-A-EM-USO', MedicationStatus.IN_USE)
        remedio(e, 'MEDORD-C-CONCLUIDA', MedicationStatus.FINISHED)
        remedio(e, 'MEDORD-D-EM-USO', MedicationStatus.IN_USE)
        remedio(e, 'MEDORD-AA-SUSPENSA', MedicationStatus.SUSPENDED)
    ordem_meds = ['MEDORD-A-EM-USO', 'MEDORD-D-EM-USO', 'MEDORD-AA-SUSPENSA',
                  'MEDORD-B-SUSPENSA', 'MEDORD-C-CONCLUIDA']
    Encounter.objects.filter(id=anterior.id).update(
        status=EncounterStatus.FINALIZED, finalized_at=agora - datetime.timedelta(days=30),
    )

    print('=== 1. a aba do atendimento ===')
    r = doc.get(f'/app/clinical/{enc.id}/')
    confere(r.status_code == 200, f'o atendimento abre ({r.status_code})')
    corpo = r.content.decode()
    em_ordem(corpo, ordem_exames, 'exames, mais recente em cima e sem data no fim')
    inicio_meds = corpo.find('id="tab-medicacoes"')
    trecho = corpo[inicio_meds:] if inicio_meds >= 0 else corpo
    em_ordem(trecho, ordem_meds, 'medicações agrupadas por situação')

    print('=== 2. a gaveta da consulta anterior ===')
    inicio = corpo.find('Medicação registrada')
    confere(inicio >= 0, 'a gaveta mostra a medicação da consulta anterior')
    em_ordem(corpo[inicio:], ordem_meds, 'gaveta agrupada por situação')

    print('=== 3. os resumos ===')
    r = doc.get(f'/app/clinical/{enc.id}/resumo/')
    confere(r.status_code == 200, f'o resumo do atendimento abre ({r.status_code})')
    resumo = r.content.decode()
    em_ordem(resumo, ordem_exames, 'resumo: exames')
    em_ordem(resumo, ordem_meds, 'resumo: medicações')
    r = doc.get(f'/app/clinical/patients/{paciente.id}/resumo/')
    confere(r.status_code == 200, f'o resumo de todos abre ({r.status_code})')
    todos = r.content.decode()
    em_ordem(todos, ordem_exames, 'resumo de todos: exames')
    em_ordem(todos, ordem_meds, 'resumo de todos: medicações do atendimento mais recente')

    print('=== 4. a IA lê os mais recentes ===')
    autorizacao = SimpleNamespace(tenant_id=clinica.id, patient_id=paciente.id)
    linhas = get_exam_results(autorizacao, limit=2)
    nomes = [linha['exam'] for linha in linhas]
    confere(nomes == [EX_NOV, EX_OUT_TARDE], f'as duas vagas vão aos dois mais recentes ({nomes})')

    print('=== 5. as chaves das listas já carregadas (acervo) ===')
    exames = list(ExamResult.objects.filter(encounter=enc))
    confere([e.name for e in sorted(exames, key=chave_do_exame)] == ordem_exames,
            'chave_do_exame dá a mesma ordem da consulta')
    meds = list(Medication.objects.filter(encounter=enc))
    confere([m.name for m in sorted(meds, key=chave_da_medicacao)] == ordem_meds,
            'chave_da_medicacao dá a mesma ordem da consulta')
    estranha = SimpleNamespace(status='inexistente', name='A')
    confere(chave_da_medicacao(estranha)[0] == 3, 'situação desconhecida vai para o fim sem erro')
finally:
    ExamResult.objects.filter(encounter_id__in=encontros).delete()
    Medication.objects.filter(encounter_id__in=encontros).delete()
    Encounter.objects.filter(id__in=encontros).delete()
    Patient.objects.filter(id=paciente.id).delete()

if falhas:
    print(f'\nFALHA: {len(falhas)} problema(s):')
    for f in falhas:
        print(f'  - {f}')
    raise SystemExit(1)
print('\nOK: exames do mais recente ao mais antigo (sem data no fim) e medicações agrupadas por situação.')
