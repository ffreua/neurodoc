"""Exames da consulta anterior, trazidos por escolha do medico (2026-11-26).

O pedido: no retorno, alem da conduta, das impressoes, das hipoteses e da
medicacao, poder trazer da consulta anterior **tambem os exames** -- e o
medico escolhe o que traz.

O desenho que este roteiro defende: o exame trazido e um **vinculo**
(`EncounterExamLink`) para o mesmo `ExamResult`, nunca uma copia. Copiado,
o mesmo hemograma apareceria duas vezes na lista de exames do paciente, na
curva de evolucao dos analitos e no que a IA le.

O que se cobra, e onde daria errado:

1. a copia oferece cada exame da consulta anterior como item proprio, com
   data e tipo legiveis, e nao oferece o que ja esta nesta consulta;
2. aceitar vincula, recusar nao, aceitar duas vezes nao duplica, e **nenhum
   `ExamResult` novo nasce** -- a lista do paciente e a da IA ficam iguais;
3. a tela mostra o trazido, so de leitura, nos dois tipos de atendimento,
   e o resumo impresso diz de qual consulta ele veio;
4. o exame acompanha o paciente de retorno em retorno (o trazido e oferecido
   de novo no retorno seguinte), e o recusado nao volta;
5. um item com o id de exame de **outro paciente** nao vincula nada, e o
   banco recusa o vinculo para exame de outra clinica;
6. retirar desta consulta apaga so o vinculo; finalizado recusa, `GET` nao
   faz nada, secretaria e outra clinica nao alcancam;
7. descartar o rascunho leva os vinculos e deixa o exame.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import datetime

from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from accounts.models import User
from ai.context import AIAuthorization
from ai.tools import clinical as clinical_tools
from clinical import carry_forward as cf
from clinical import finalization
from clinical.models import (
    CarryForwardItem, Encounter, EncounterExamLink, EncounterKind, EncounterStatus,
    ExamCategory, ExamResult, LabValue, ReviewAction,
)
from patients.models import Patient, PatientStatus, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []
CHR = chr(10)


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:66} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


clinica = Tenant.objects.get(slug='demo-clinica-a')
clinica_b = Tenant.objects.get(slug='demo-clinica-b')
medico = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
).select_related('user').first()
secretaria = Membership.objects.filter(
    tenant=clinica, roles__contains=[Role.SECRETARY], status=MembershipStatus.ACTIVE,
).select_related('user').first()
medico_b = Membership.objects.filter(
    tenant=clinica_b, roles__contains=[Role.DOCTOR], status=MembershipStatus.ACTIVE,
).select_related('user').first()


def logado(vinculo, tenant):
    c = Client()
    c.force_login(vinculo.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


class Contexto:
    tenant_id = clinica.id
    user_id = medico.user_id
    membership_id = medico.id


pacientes, atendimentos = [], []


def novo_paciente(nome, tenant=clinica):
    p = Patient.objects.create(
        tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
        status=PatientStatus.ACTIVE, birth_date_unknown_reason='Roteiro de verificacao.',
    )
    pacientes.append(p)
    return p


def consulta(paciente, dias_atras, status=EncounterStatus.FINALIZED, kind=EncounterKind.FREE_TEXT,
             vinculo=None, tenant=clinica):
    e = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=vinculo or medico,
        occurred_at=timezone.now() - datetime.timedelta(days=dias_atras), status=status, kind=kind,
        free_text='Consulta do roteiro.',
    )
    atendimentos.append(e)
    return e


def exame(encounter, nome, dias, categoria=ExamCategory.LABORATORY, conclusao=''):
    return ExamResult.objects.create(
        tenant=encounter.tenant, encounter=encounter, patient=encounter.patient, category=categoria,
        name=nome, performed_on=timezone.localdate() - datetime.timedelta(days=dias),
        conclusion=conclusao,
    )


def itens_de_exame(encounter):
    return {
        i.field_path: i for i in
        CarryForwardItem.objects.filter(target_encounter=encounter, field_path__startswith='exam:')
    }


def revisar(cliente, encounter, item, acao):
    return cliente.post(
        f'/app/clinical/{encounter.id}/carry-forward/{item.id}/review/', {'action': acao},
    )


medico_cli = logado(medico, clinica)

try:
    print(CHR + '1. A copia oferece os exames da consulta anterior, um a um')
    pac = novo_paciente('ROTEIRO EXAMES TRAZIDOS')
    anterior = consulta(pac, 40)
    hemo = exame(anterior, 'Hemograma completo', 41, conclusao='Anemia leve.')
    LabValue.objects.create(
        tenant=clinica, exam_result=hemo, analyte='Hemoglobina', value_text='11,2',
        numeric_value=11.2, unit='g/dL', reference_low=12, reference_high=16, flag='low', order=0,
    )
    rm = exame(anterior, 'RM de cranio', 45, categoria=ExamCategory.IMAGING,
               conclusao='Sem alteracoes agudas.')
    tsh = exame(anterior, 'TSH', 42)
    retorno = consulta(pac, 0, status=EncounterStatus.DRAFT)
    cf.carry_forward(Contexto(), retorno, anterior)
    itens = itens_de_exame(retorno)
    conferir('um item por exame', sorted(itens), sorted(f'exam:{e.id}' for e in (hemo, rm, tsh)))
    descrito = cf.describe_item(itens[f'exam:{hemo.id}'])
    conferir('o rotulo e de exame', descrito['label'], 'Exame da consulta anterior')
    conferir('o valor e o nome do exame', descrito['value'], 'Hemograma completo')
    conferir('o detalhe traz a data em dd/mm/aaaa e a conclusao',
             hemo.performed_on.strftime('%d/%m/%Y') in descrito['detail']
             and 'Anemia leve.' in descrito['detail'], True)
    conferir('a tela de revisao mostra o exame pendente',
             'Hemograma completo' in medico_cli.get(f'/app/clinical/{retorno.id}/').content.decode(),
             True)

    print(CHR + '2. Aceitar vincula; recusar nao; nada e copiado')
    exames_antes = ExamResult.objects.filter(patient=pac).count()
    autorizacao = AIAuthorization(
        tenant_id=clinica.id, user_id=medico.user_id, membership_id=medico.id,
        patient_id=pac.id, encounter_id=None,
    )
    ia_antes = len(clinical_tools.get_exam_results(autorizacao))
    r1 = revisar(medico_cli, retorno, itens[f'exam:{hemo.id}'], ReviewAction.ACCEPTED)
    r2 = revisar(medico_cli, retorno, itens[f'exam:{rm.id}'], ReviewAction.ACCEPTED)
    r3 = revisar(medico_cli, retorno, itens[f'exam:{tsh.id}'], ReviewAction.REJECTED)
    conferir('as tres revisoes voltam para a tela', [r1.status_code, r2.status_code, r3.status_code],
             [302, 302, 302])
    vinculados = set(retorno.exam_links.values_list('exam_result_id', flat=True))
    conferir('o aceito vira vinculo e o recusado nao', vinculados, {hemo.id, rm.id})
    conferir('nenhum ExamResult novo no paciente',
             ExamResult.objects.filter(patient=pac).count(), exames_antes)
    conferir('e a IA le os mesmos exames, sem duplicar',
             len(clinical_tools.get_exam_results(autorizacao)), ia_antes)
    cf.review_carry_forward_item(
        CarryForwardItem.objects.get(id=itens[f'exam:{hemo.id}'].id), ReviewAction.ACCEPTED, medico.id,
    )
    conferir('aceitar de novo nao duplica o vinculo', retorno.exam_links.count(), 2)

    print(CHR + '3. A tela e o resumo mostram o trazido')
    pagina = medico_cli.get(f'/app/clinical/{retorno.id}/').content.decode()
    conferir('a secao dos trazidos aparece', 'Trazidos de consultas anteriores' in pagina, True)
    conferir('com o exame e a consulta de origem',
             'RM de cranio' in pagina and anterior.occurred_at.strftime('%d/%m/%Y') in pagina, True)
    conferir('o botao de retirar esta la', 'Retirar desta consulta' in pagina, True)
    conferir('o cartao de exames tem a ancora da aba', 'id="tab-exames"' in pagina, True)
    conferir('e a lista vazia nao aparece junto',
             'Nenhum resultado de exame registrado neste atendimento.' in pagina, False)
    if hasattr(EncounterKind, 'STRUCTURED'):
        estruturado = consulta(pac, 0, status=EncounterStatus.DRAFT, kind=EncounterKind.STRUCTURED)
        EncounterExamLink.objects.create(
            tenant=clinica, encounter=estruturado, exam_result=hemo, source_encounter=anterior,
        )
        pagina_e = medico_cli.get(f'/app/clinical/{estruturado.id}/').content.decode()
        conferir('no estruturado tambem, e a aba conta o trazido',
                 'Trazidos de consultas anteriores' in pagina_e
                 and 'Resultados de exames' in pagina_e, True)
    resumo = medico_cli.get(f'/app/clinical/{retorno.id}/resumo/')
    texto_resumo = resumo.content.decode()
    conferir('o resumo do atendimento abre', resumo.status_code, 200)
    conferir('e diz de que consulta o exame veio',
             'trazido da consulta de ' + anterior.occurred_at.strftime('%d/%m/%Y') in texto_resumo, True)
    conferir('com o analito fora da referencia', 'Hemoglobina' in texto_resumo, True)
    todos = medico_cli.get(f'/app/clinical/patients/{pac.id}/resumo/')
    conferir('o resumo de todos tambem traz',
             todos.status_code == 200 and 'trazido da consulta de' in todos.content.decode(), True)

    print(CHR + '4. De retorno em retorno, e o recusado nao volta')
    Encounter.objects.filter(id=retorno.id).update(status=EncounterStatus.FINALIZED)
    retorno.refresh_from_db()
    proximo = consulta(pac, -1, status=EncounterStatus.DRAFT)
    Encounter.objects.filter(id=proximo.id).update(occurred_at=timezone.now() + datetime.timedelta(minutes=5))
    proximo.refresh_from_db()
    conferir('a origem padrao e o retorno finalizado',
             cf.default_source_encounter(proximo).id if cf.default_source_encounter(proximo) else None,
             retorno.id)
    cf.carry_forward(Contexto(), proximo)
    conferir('o trazido e oferecido de novo, o recusado nao',
             sorted(itens_de_exame(proximo)), sorted(f'exam:{e.id}' for e in (hemo, rm)))
    EncounterExamLink.objects.create(
        tenant=clinica, encounter=proximo, exam_result=rm, source_encounter=retorno,
    )
    CarryForwardItem.objects.filter(target_encounter=proximo).delete()
    cf.carry_forward(Contexto(), proximo)
    conferir('o que ja esta nesta consulta nao vira item',
             sorted(itens_de_exame(proximo)), [f'exam:{hemo.id}'])

    print(CHR + '5. Exame de outro paciente ou de outra clinica nao entra')
    outro_pac = novo_paciente('ROTEIRO OUTRO PACIENTE')
    alheio = exame(consulta(outro_pac, 10), 'Exame de outro paciente', 10)
    forjado = CarryForwardItem.objects.create(
        tenant=clinica, target_encounter=proximo, source_encounter=retorno,
        field_path=f'exam:{alheio.id}', source_version_hash='x', copied_value={'name': 'forjado'},
    )
    cf.review_carry_forward_item(forjado, ReviewAction.ACCEPTED, medico.id)
    conferir('o id de exame de outro paciente nao vincula',
             proximo.exam_links.filter(exam_result=alheio).exists(), False)
    pac_b = novo_paciente('ROTEIRO CLINICA B', tenant=clinica_b)
    exame_b = exame(consulta(pac_b, 5, vinculo=medico_b, tenant=clinica_b), 'Exame da clinica B', 5)
    try:
        with transaction.atomic():
            EncounterExamLink.objects.create(
                tenant=clinica, encounter=proximo, exam_result=exame_b, source_encounter=retorno,
            )
        recusado = False
    except IntegrityError:
        recusado = True
    conferir('o banco recusa vinculo a exame de outra clinica', recusado, True)

    print(CHR + '6. Retirar: so o vinculo, e so quem pode')
    link_rm = proximo.exam_links.get(exam_result=rm)
    url = f'/app/clinical/{proximo.id}/exames-trazidos/{link_rm.id}/retirar/'
    conferir('GET nao retira', medico_cli.get(url).status_code in (404, 405), True)
    conferir('e o vinculo continua', EncounterExamLink.objects.filter(id=link_rm.id).exists(), True)
    if secretaria is not None:
        r = logado(secretaria, clinica).post(url)
        conferir('a secretaria nao retira', r.status_code in (403, 404), True)
    if medico_b is not None:
        r = logado(medico_b, clinica_b).post(url)
        conferir('outra clinica nao alcanca', r.status_code in (403, 404), True)
    conferir('o vinculo segue intacto', EncounterExamLink.objects.filter(id=link_rm.id).exists(), True)
    r = medico_cli.post(url)
    conferir('o medico retira e volta para a aba de exames',
             (r.status_code, r.get('Location', '').endswith('#tab-exames')), (302, True))
    conferir('o vinculo saiu', EncounterExamLink.objects.filter(id=link_rm.id).exists(), False)
    conferir('e o exame continua na consulta de origem', ExamResult.objects.filter(id=rm.id).exists(), True)
    link_fin = retorno.exam_links.get(exam_result=hemo)
    r = medico_cli.post(f'/app/clinical/{retorno.id}/exames-trazidos/{link_fin.id}/retirar/')
    conferir('na consulta finalizada a retirada e recusada',
             EncounterExamLink.objects.filter(id=link_fin.id).exists(), True)
    conferir('e a finalizada nao mostra o botao',
             'Retirar desta consulta' in medico_cli.get(f'/app/clinical/{retorno.id}/').content.decode(),
             False)

    print(CHR + '7. Descartar o rascunho leva os vinculos e deixa o exame')
    rascunho = consulta(pac, -2, status=EncounterStatus.DRAFT)
    EncounterExamLink.objects.create(
        tenant=clinica, encounter=rascunho, exam_result=hemo, source_encounter=retorno,
    )
    finalization.discard_encounter(Contexto(), rascunho, medico, reason='Roteiro de verificacao.')
    conferir('o rascunho saiu', Encounter.objects.filter(id=rascunho.id).exists(), False)
    conferir('o vinculo saiu junto', EncounterExamLink.objects.filter(encounter_id=rascunho.id).exists(), False)
    conferir('e o exame ficou', ExamResult.objects.filter(id=hemo.id).exists(), True)
    atendimentos.remove(rascunho)

finally:
    ids = [e.id for e in atendimentos]
    EncounterExamLink.objects.filter(encounter_id__in=ids).delete()
    CarryForwardItem.objects.filter(target_encounter_id__in=ids).delete()
    LabValue.objects.filter(exam_result__encounter_id__in=ids).delete()
    ExamResult.objects.filter(encounter_id__in=ids).delete()
    from audit.models import AuditEvent  # noqa: F401  (a trilha e imutavel; fica)
    Encounter.objects.filter(id__in=ids).delete()
    Patient.objects.filter(id__in=[p.id for p in pacientes]).delete()
    print(f'{CHR}  limpeza: {len(ids)} atendimento(s) e {len(pacientes)} paciente(s) de roteiro removidos')

if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print(CHR + 'OK: o exame da consulta anterior entra por escolha do medico, como vinculo,')
print('    sem duplicar, so do mesmo paciente, e sai sem apagar o exame.')
