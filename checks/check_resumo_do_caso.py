"""Resumo do caso: deste atendimento ou de todos, o mais recente primeiro (1.42).

O pedido: no botão "Resumo do caso", a opção do atendimento atual ou de todos
os atendimentos; em todos, o último em primeiro lugar e os demais na
sequência.

O que o roteiro tenta quebrar:

1. **a ordem**: o mais recente no topo, e os outros do mais novo ao mais
   antigo — conferida pela posição de cada atendimento na página;
2. **cada um com o que é dele**: a medicação, a hipótese, o adendo e o
   achado de um atendimento não aparecem dentro de outro (o lote agrupa por
   atendimento, e um erro de agrupamento espalharia o prontuário);
3. **os três tipos** desenhados como na folha de um atendimento: a história
   da primeira consulta, a evolução do seguimento e o corpo do texto livre;
4. **o número de consultas não cresce** com o número de atendimentos (2 e 8
   medem igual) — o paciente vindo do iClin tem dezenas;
5. **a folha de um atendimento continua a mesma**, agora com o link para
   todos;
6. **os botões** nas duas telas de atendimento, com as duas opções, no
   computador e no celular;
7. **a fronteira**: outra clínica e a secretária não abrem, e a leitura vai
   para a trilha; o paciente sem atendimento abre a folha vazia.

Tudo dentro de uma transação desfeita no fim.
"""
import re
import secrets
from datetime import date, timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import (
    ClinicalAmendment, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus,
    EstruturaDoAtendimento, ExaminationFinding, Medication,
)
from patients.models import Patient
from tenancy.models import Membership, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


tenant = Tenant.objects.get(slug='demo-clinica-a')
outro_tenant = Tenant.objects.get(slug='demo-clinica-b')
medico = User.objects.get(email='doctor-a@demo.neurodoc.local')
vinculo = Membership.objects.get(tenant=tenant, user=medico)
secretaria = User.objects.filter(
    memberships__tenant=tenant, memberships__roles__contains=['secretary'],
).exclude(memberships__roles__contains=['doctor']).first()
medico_b = User.objects.filter(
    memberships__tenant=outro_tenant, memberships__roles__contains=['doctor'],
).first()


def cliente_de(usuario, dono=tenant):
    c = Client()
    c.force_login(usuario)
    s = c.session
    s['tenant_id'] = str(dono.id)
    s.save()
    return c


def cpf_valido():
    while True:
        base = [secrets.randbelow(10) for _ in range(9)]
        for _ in range(2):
            soma = sum(d * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
            base.append((soma * 10 % 11) % 10)
        texto = ''.join(map(str, base))
        if len(set(texto)) > 1 and not Patient.objects.filter(cpf=texto).exists():
            return texto


def novo_paciente():
    return Patient.objects.create(
        tenant=tenant, full_name=f'PACIENTE RESUMO {secrets.token_hex(3).upper()}',
        birth_date=date(1970, 1, 2), cpf=cpf_valido(), sex_at_registration='female',
    )


def atendimento(paciente, dias_atras, marca, **campos):
    """Um atendimento com medicação, hipótese, achado e adendo marcados."""
    dados = {
        'tenant': tenant, 'patient': paciente, 'physician_membership': vinculo,
        'occurred_at': timezone.now() - timedelta(days=dias_atras),
        'status': EncounterStatus.FINALIZED, 'finalized_at': timezone.now() - timedelta(days=dias_atras),
        'finalized_by': vinculo, 'kind': EncounterKind.STRUCTURED, 'plan_text': f'CONDUTA-{marca}',
    }
    dados.update(campos)
    e = Encounter.objects.create(**dados)
    e.content_hash = e.compute_content_hash()
    e.save(update_fields=['content_hash'])
    Medication.objects.create(tenant=tenant, encounter=e, name=f'REMEDIO-{marca}', dose='10 mg')
    EncounterDiagnosis.objects.create(tenant=tenant, encounter=e, code_snapshot='G40',
                                      description_snapshot=f'HIPOTESE-{marca}', certainty='confirmed', rank=1)
    ExaminationFinding.objects.create(tenant=tenant, encounter=e, domain='escalas',
                                      item_code=f'escala.teste{marca.lower()}', qualifier=f'ACHADO-{marca}',
                                      value_json={'name': f'ESCALA-{marca}'}, numeric_value=1)
    if e.status == EncounterStatus.FINALIZED:
        ClinicalAmendment.objects.create(tenant=tenant, encounter=e, author=vinculo,
                                         reason=f'ADENDO-{marca}', text='Complemento.',
                                         authored_at=timezone.now())
    return e


class _Desfaz(Exception):
    pass


try:
    with transaction.atomic():
        c = cliente_de(medico)
        p = novo_paciente()
        primeira = atendimento(p, 300, 'A', chief_complaint='QUEIXA-A', hpi='HISTORIA-A')
        seguimento = atendimento(p, 120, 'B', estrutura=EstruturaDoAtendimento.SEGUIMENTO,
                                 evolucao='EVOLUCAO-B')
        livre = atendimento(p, 2, 'C', kind=EncounterKind.FREE_TEXT, free_text='TEXTOLIVRE-C',
                            status=EncounterStatus.DRAFT, finalized_at=None, finalized_by=None)
        url = reverse('clinical:resumo-todos', args=[p.id])

        print('\n1. A ordem: o mais recente primeiro')
        r = c.get(url)
        html = r.content.decode()
        conferir('a folha abre', r.status_code == 200, r.status_code)
        secoes = [m.start() for m in re.finditer(r'<section class="atendimento"', html)]
        conferir('uma seção por atendimento', len(secoes) == 3, len(secoes))
        pos = {m: html.find(f'CONDUTA-{m}') for m in 'ABC'}
        conferir('o texto livre de anteontem vem primeiro, a primeira consulta por último',
                 0 < pos['C'] < pos['B'] < pos['A'], pos)
        conferir('o sumário na mesma ordem',
                 re.search(r'1\.</span>\s*<a href="#atendimento-1">\s*'
                           + livre.occurred_at.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y'), html)
                 is not None)

        print('\n2. Cada atendimento com o que é dele')
        fins = secoes[1:] + [len(html)]
        for indice, marca in enumerate('CBA'):
            trecho = html[secoes[indice]:fins[indice]]
            outras = [m for m in 'ABC' if m != marca]
            for coisa in ('REMEDIO', 'HIPOTESE', 'ESCALA'):
                conferir(f'{marca}: a {coisa.lower()} dele está nele', f'{coisa}-{marca}' in trecho)
                conferir(f'{marca}: e não a dos outros',
                         not any(f'{coisa}-{o}' in trecho for o in outras))
            if marca != 'C':
                conferir(f'{marca}: o adendo dele', f'ADENDO-{marca}' in trecho
                         and not any(f'ADENDO-{o}' in trecho for o in outras))

        print('\n3. Os três tipos como na folha de um atendimento')
        trecho_a = html[secoes[2]:]
        trecho_b = html[secoes[1]:secoes[2]]
        trecho_c = html[secoes[0]:secoes[1]]
        conferir('primeira consulta: queixa e história', 'QUEIXA-A' in trecho_a and 'HISTORIA-A' in trecho_a)
        conferir('seguimento: a evolução, sem queixa', '<h2>Evolução</h2>' in trecho_b and 'EVOLUCAO-B' in trecho_b
                 and 'Queixa principal' not in trecho_b)
        conferir('texto livre: o corpo', 'TEXTOLIVRE-C' in trecho_c and 'Queixa principal' not in trecho_c)
        conferir('o tipo no cabeçalho de cada um', 'Texto livre' in trecho_c and 'Seguimento e retorno' in trecho_b
                 and 'Primeira consulta' in trecho_a)
        conferir('o aberto sai marcado como editável', 'ainda editável' in trecho_c)
        conferir('o finalizado com o hash', primeira.content_hash[:16] in trecho_a)
        conferir('não é documento assinado', 'não é documento assinado' in html)

        print('\n4. O número de consultas não cresce com o volume')
        def medir(n):
            q = novo_paciente()
            for i in range(n):
                atendimento(q, 10 + i, f'Q{i}')
            with CaptureQueriesContext(connection) as consultas:
                resposta = c.get(reverse('clinical:resumo-todos', args=[q.id]))
            return resposta.status_code, len(consultas)
        (s2, n2), (s8, n8) = medir(2), medir(8)
        conferir('2 e 8 atendimentos: o mesmo número de consultas', s2 == s8 == 200 and n2 == n8, f'{n2} × {n8}')

        print('\n5. A folha de um atendimento continua a mesma')
        um = c.get(reverse('clinical:summary', args=[seguimento.id])).content.decode()
        conferir('só o atendimento dela', 'EVOLUCAO-B' in um and 'CONDUTA-A' not in um and 'CONDUTA-C' not in um)
        conferir('com as seções de sempre', all(t in um for t in (
            'Medicações em uso', 'Resultados de exames', 'Hipóteses diagnósticas', 'Conduta', 'Adendos')))
        conferir('e o link para todos', url in um)

        print('\n6. Os botões nas duas telas de atendimento')
        for nome, e in [('estruturado', seguimento), ('texto livre', livre)]:
            tela = c.get(reverse('clinical:detail', args=[e.id])).content.decode()
            conferir(f'{nome}: este atendimento', reverse('clinical:summary', args=[e.id]) in tela)
            conferir(f'{nome}: todos os atendimentos', url in tela and 'Todos os atendimentos' in tela)
            conferir(f'{nome}: as duas opções no celular',
                     'Resumo deste atendimento' in tela and 'Resumo de todos os atendimentos' in tela)
            conferir(f'{nome}: em janela própria', tela.count('data-nd-window="resumo"') >= 4)
        conferir('o comportamento da janela vale nas duas telas (nd-inline.js)',
                 "closest('[data-nd-window]')" in open(dj_settings.BASE_DIR / 'static/duralux/nd-inline.js',
                                                         encoding='utf-8').read())

        print('\n7. Fronteira e trilha')
        conferir('a leitura vai para a trilha', AuditEvent.objects.filter(
            action='clinical.patient_summary_viewed', object_id=p.id).exists())
        if medico_b:
            conferir('outra clínica: 404', cliente_de(medico_b, outro_tenant).get(url).status_code == 404)
        if secretaria:
            conferir('a secretária não abre', cliente_de(secretaria).get(url).status_code in (403, 404))
        vazio = novo_paciente()
        r = c.get(reverse('clinical:resumo-todos', args=[vazio.id]))
        conferir('paciente sem atendimento: folha vazia, sem erro',
                 r.status_code == 200 and 'Nenhum atendimento registrado' in r.content.decode())
        conferir('POST não é aceito', c.post(url).status_code in (403, 405))

        raise _Desfaz
except _Desfaz:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} item(ns)')
    for f in falhas:
        print('  -', f)
    raise SystemExit(1)
print('OK: o resumo deste atendimento e o de todos, do mais recente ao primeiro.')
