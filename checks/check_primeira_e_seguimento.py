"""Primeira consulta, seguimento e texto livre; escalas no texto livre; o código em casas (1.41).

O pedido: o "Novo atendimento" abre a primeira consulta, com queixa e
história; o seguimento e retorno troca as duas pela **Evolução** e mantém o
resto; o texto livre continua o mesmo, agora com as **escalas** — para a série
do gráfico de evolução receber também o retorno rápido. E o código do segundo
fator em casas individuais, em toda tela que o pede.

O que o roteiro tenta quebrar:

1. **o hash dos atendimentos fechados antes da 1.41** — recalculado, tem de
   dar o mesmo de sempre (a evolução vazia não entra); com evolução, muda;
2. **os três botões**: `structured`, `seguimento` e `free_text` abrem o que
   dizem, o valor desconhecido cai na primeira consulta, e o formulário velho
   (só `structured`) continua abrindo a primeira consulta;
3. **a tela do seguimento**: a aba se chama Evolução, tem o campo e não tem
   queixa nem história, e o resto (antecedentes, hábitos, consanguinidade e
   as outras abas) continua; ao lado, a queixa e a história da primeira
   consulta, para ler;
4. **a finalização** do seguimento cobra a evolução, e não a queixa;
5. **a troca de tipo** enquanto aberto, recusada quando esconderia texto,
   no finalizado e no texto livre, e só por POST;
6. **a sugestão** do botão principal: o horário de hoje com check-in manda;
   sem ele, o histórico;
7. **as duas portas** (ficha e prontuário) com os três tipos, o sugerido
   marcado, e a secretária sem o botão;
8. **as escalas no texto livre**: o cartão, o `exam.js`, gravar volta para
   `#escalas`, e a escala entra na série do gráfico de evolução;
9. **o resto do sistema lê a evolução**: a IA (linha do tempo, chat, apoio
   diagnóstico), a exportação, o resumo impresso, a gaveta da consulta
   anterior, a lista de atendimentos e o descarte;
10. **o código em casas**: o campo de entrar e de reconfirmar com as seis
    casas e a troca para o código de recuperação, a configuração e o reset
    da equipe com as casas, e o script nos dois moldes de página.

Tudo dentro de uma transação desfeita no fim.
"""
import hashlib
import re
import secrets
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from clinical import estrutura, finalization, selectors
from clinical.models import (
    Encounter, EncounterKind, EncounterStatus, EstruturaDoAtendimento, ExaminationFinding,
)
from exams.models import ExamScale
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
        tenant=tenant, full_name=f'PACIENTE SEGUIMENTO {secrets.token_hex(3).upper()}',
        birth_date=date(1975, 3, 9), cpf=cpf_valido(), sex_at_registration='female',
    )


def atendimento(paciente, **campos):
    dados = {
        'tenant': tenant, 'patient': paciente, 'physician_membership': vinculo,
        'occurred_at': timezone.now(), 'status': EncounterStatus.DRAFT,
        'kind': EncounterKind.STRUCTURED,
    }
    dados.update(campos)
    return Encounter.objects.create(**dados)


def fechar(e):
    e.status = EncounterStatus.FINALIZED
    e.finalized_at = timezone.now()
    e.finalized_by = vinculo
    e.content_hash = e.compute_content_hash()
    e.save()
    return e


def hash_da_140(e):
    """A fórmula da 1.40, copiada: o que estava gravado nos fechados."""
    payload = '|'.join([
        e.chief_complaint, e.hpi, e.personal_history, e.family_history, e.habits_history,
        e.consanguinity_state, e.consanguinity_details, e.neurological_exam_text, e.plan_text,
        e.free_text, e.impressions,
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


def abrir_pelo_botao(cliente, paciente, valor):
    antes = set(Encounter.objects.filter(patient=paciente).values_list('id', flat=True))
    r = cliente.post(reverse('clinical:new', args=[paciente.id]), {'kind': valor})
    novo = Encounter.objects.filter(patient=paciente).exclude(id__in=antes).first()
    return r, novo


class _Desfaz(Exception):
    pass


try:
    with transaction.atomic():
        c = cliente_de(medico)

        print('\n1. O hash dos atendimentos fechados antes da 1.41 não muda')
        p0 = novo_paciente()
        velho = atendimento(p0, chief_complaint='Cefaleia', hpi='Há três meses.', plan_text='Diário.')
        conferir('sem evolução, o hash é o da 1.40', velho.compute_content_hash() == hash_da_140(velho))
        velho.evolucao = 'Melhorou.'
        conferir('com evolução, o hash muda', velho.compute_content_hash() != hash_da_140(velho))
        livre_velho = atendimento(p0, kind=EncounterKind.FREE_TEXT, free_text='Retorno, estável.')
        conferir('texto livre antigo: o mesmo hash', livre_velho.compute_content_hash() == hash_da_140(livre_velho))
        fechados = list(Encounter.objects.filter(status=EncounterStatus.FINALIZED).exclude(content_hash='')[:300])
        divergentes = [e.id for e in fechados if e.compute_content_hash() != e.content_hash]
        conferir(f'{len(fechados)} fechados do banco recalculam igual ao gravado', not divergentes,
                 f'{len(divergentes)} divergentes' if divergentes else '')

        print('\n2. Os três botões abrem o que dizem')
        p1 = novo_paciente()
        for valor, kind, estr in [
            ('structured', EncounterKind.STRUCTURED, EstruturaDoAtendimento.PRIMEIRA),
            ('seguimento', EncounterKind.STRUCTURED, EstruturaDoAtendimento.SEGUIMENTO),
            ('free_text', EncounterKind.FREE_TEXT, EstruturaDoAtendimento.PRIMEIRA),
            ('chute', EncounterKind.STRUCTURED, EstruturaDoAtendimento.PRIMEIRA),
        ]:
            r, e = abrir_pelo_botao(c, p1, valor)
            conferir(f'kind={valor} → {kind}/{estr}', e is not None and (e.kind, e.estrutura) == (kind, estr),
                     f'{r.status_code} {e and (e.kind, e.estrutura)}')
        conferir('rótulos dos três tipos', [
            Encounter(kind='structured', estrutura='primeira').rotulo_do_tipo,
            Encounter(kind='structured', estrutura='seguimento').rotulo_do_tipo,
            Encounter(kind='free_text', estrutura='seguimento').rotulo_do_tipo,
        ] == ['Primeira consulta', 'Seguimento e retorno', 'Texto livre'])
        conferir('texto livre nunca é seguimento',
                 not Encounter(kind='free_text', estrutura='seguimento').eh_seguimento)

        print('\n3. A tela do seguimento')
        p2 = novo_paciente()
        primeira = fechar(atendimento(
            p2, occurred_at=timezone.now() - timedelta(days=90),
            chief_complaint='QUEIXA-MARCADORA tremor de repouso',
            hpi='HISTORIA-MARCADORA iniciou há dois anos na mão direita.', plan_text='Levodopa.',
        ))
        seg = atendimento(p2, estrutura=EstruturaDoAtendimento.SEGUIMENTO)
        html = c.get(reverse('clinical:detail', args=[seg.id])).content.decode()
        conferir('a primeira aba se chama Evolução',
                 re.search(r'data-bs-target="#tab-historia"[^>]*>\s*Evolução<', html) is not None)
        conferir('tem o campo da evolução', 'id="id_evolucao"' in html)
        conferir('não tem queixa nem história', 'id="id_chief_complaint"' not in html and 'id="id_hpi"' not in html)
        for campo in ('personal_history', 'family_history', 'habits_history', 'consanguinity_state',
                      'consanguinity_details'):
            conferir(f'continua com {campo}', f'id="id_{campo}"' in html)
        for aba in ('tab-medicacoes', 'tab-exame', 'tab-exames', 'tab-hipoteses', 'tab-conduta'):
            conferir(f'continua com a aba {aba}', f'id="{aba}"' in html)
        conferir('o botão diz "Salvar evolução"', 'Salvar evolução' in html)
        conferir('ao lado, a queixa da primeira consulta', 'QUEIXA-MARCADORA' in html)
        conferir('e a história dela', 'HISTORIA-MARCADORA' in html)
        conferir('com a data dela', primeira.occurred_at.astimezone(timezone.get_current_timezone()).strftime('%d/%m/%Y') in html)
        html_p = c.get(reverse('clinical:detail', args=[primeira.id])).content.decode()
        conferir('a primeira consulta continua com queixa e história',
                 'id="id_chief_complaint"' in html_p and 'id="id_hpi"' in html_p and 'id="id_evolucao"' not in html_p)
        r = c.post(reverse('clinical:autosave', args=[seg.id]), {
            'row_version': seg.row_version, 'evolucao': 'Sem tremor desde o ajuste.', 'aba': 'tab-historia',
        })
        seg.refresh_from_db()
        conferir('a evolução grava pelo autosave', seg.evolucao == 'Sem tremor desde o ajuste.', r.status_code)
        conferir('e volta para a aba', r.headers.get('Location', '').endswith('#tab-historia'))
        conferir('sem tocar na queixa', seg.chief_complaint == '' and seg.hpi == '')

        print('\n4. A finalização do seguimento cobra a evolução')
        vazio = atendimento(p2, estrutura=EstruturaDoAtendimento.SEGUIMENTO, plan_text='Manter.')
        textos = [item['texto'] for item in finalization.missing_requirements(vazio)]
        conferir('sem evolução, pede a evolução', 'Escrever a evolução.' in textos, textos)
        conferir('e não pede queixa nem história', not any('queixa' in t for t in textos), textos)
        seg.plan_text = 'Manter levodopa.'
        seg.save()
        ctx = SimpleNamespace(tenant_id=tenant.id, user_id=medico.id, membership_id=vinculo.id)
        fechado = finalization.finalize_encounter(ctx, seg, vinculo)
        conferir('com evolução e conduta, finaliza', fechado.status == EncounterStatus.FINALIZED)
        conferir('o hash cobre a evolução', fechado.content_hash == fechado.compute_content_hash()
                 and fechado.content_hash != hash_da_140(fechado))

        print('\n5. Trocar primeira consulta ↔ seguimento enquanto aberto')
        p3 = novo_paciente()
        t1 = atendimento(p3, estrutura=EstruturaDoAtendimento.SEGUIMENTO)
        url = reverse('clinical:estrutura', args=[t1.id])
        conferir('GET não troca', c.get(url).status_code == 405)
        r = c.post(url, {'estrutura': 'primeira'})
        t1.refresh_from_db()
        conferir('seguimento vazio vira primeira consulta', t1.estrutura == 'primeira' and r.status_code == 302)
        conferir('a troca vai para a trilha', AuditEvent.objects.filter(
            action='clinical.encounter_estrutura_trocada', object_id=t1.id).exists())
        t1.hpi = 'Texto já escrito.'
        t1.save()
        c.post(url, {'estrutura': 'seguimento'})
        t1.refresh_from_db()
        conferir('primeira consulta com história não vira seguimento', t1.estrutura == 'primeira')
        t2 = atendimento(p3, estrutura=EstruturaDoAtendimento.SEGUIMENTO, evolucao='Já escrito.')
        c.post(reverse('clinical:estrutura', args=[t2.id]), {'estrutura': 'primeira'})
        t2.refresh_from_db()
        conferir('seguimento com evolução não vira primeira consulta', t2.estrutura == 'seguimento')
        t3 = fechar(atendimento(p3, estrutura=EstruturaDoAtendimento.SEGUIMENTO, evolucao='', plan_text='x'))
        c.post(reverse('clinical:estrutura', args=[t3.id]), {'estrutura': 'primeira'})
        t3.refresh_from_db()
        conferir('finalizado não troca', t3.estrutura == 'seguimento')
        t4 = atendimento(p3, kind=EncounterKind.FREE_TEXT)
        c.post(reverse('clinical:estrutura', args=[t4.id]), {'estrutura': 'seguimento'})
        t4.refresh_from_db()
        conferir('texto livre não troca', t4.estrutura == 'primeira')
        c.post(reverse('clinical:estrutura', args=[t1.id]), {'estrutura': 'inventada'})
        t1.refresh_from_db()
        conferir('valor inventado não grava', t1.estrutura == 'primeira')
        if medico_b:
            r = cliente_de(medico_b, outro_tenant).post(url, {'estrutura': 'seguimento'})
            conferir('outra clínica: 404', r.status_code == 404, r.status_code)

        print('\n6. A sugestão do botão principal')
        p4 = novo_paciente()
        conferir('paciente sem atendimento: primeira consulta',
                 estrutura.abertura_sugerida(tenant.id, p4, vinculo.id) == 'structured')
        fechar(atendimento(p4, chief_complaint='x', plan_text='y', occurred_at=timezone.now() - timedelta(days=30)))
        conferir('com atendimento finalizado: seguimento',
                 estrutura.abertura_sugerida(tenant.id, p4, vinculo.id) == 'seguimento')
        from scheduling.models import Appointment, AppointmentStatus, AppointmentType

        inicio = timezone.make_aware(datetime.combine(timezone.localdate(), time(5, 7)))
        from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

        horario = Appointment.objects.create(
            tenant=tenant, patient=p4, physician_membership=vinculo, starts_at=inicio,
            ends_at=inicio + timedelta(minutes=20), status=AppointmentStatus.CHECKED_IN,
            type=AppointmentType.FIRST_VISIT,
            occupied_range=DateTimeTZRange(inicio, inicio + timedelta(minutes=20), '[)'),
        )
        conferir('check-in de hoje como primeira consulta manda',
                 estrutura.abertura_sugerida(tenant.id, p4, vinculo.id) == 'structured')
        horario.type = AppointmentType.RETURN_VISIT
        horario.save()
        p5 = novo_paciente()
        Appointment.objects.filter(id=horario.id).update(patient=p5)
        conferir('retorno de hoje é seguimento, mesmo sem histórico',
                 estrutura.abertura_sugerida(tenant.id, p5, vinculo.id) == 'seguimento')
        Appointment.objects.filter(id=horario.id).update(type=AppointmentType.PROCEDURE)
        conferir('procedimento não diz nada: vale o histórico',
                 estrutura.abertura_sugerida(tenant.id, p5, vinculo.id) == 'structured')

        print('\n7. As duas portas com os três tipos')
        for nome, rota in [('ficha', reverse('patients:detail', args=[p4.id])),
                           ('prontuário', reverse('clinical:timeline', args=[p4.id]))]:
            corpo = c.get(rota).content.decode()
            conferir(f'{nome}: os três valores', all(f'value="{v}"' in corpo for v in ('structured', 'seguimento', 'free_text')))
            conferir(f'{nome}: o menu dividido', 'dropdown-toggle-split' in corpo and 'Que atendimento é este?' in corpo)
            conferir(f'{nome}: o sugerido marcado', 'sugerido' in corpo)
            conferir(f'{nome}: a lista do celular', 'nd-novo-atendimento__lista' in corpo)
            principal = re.search(r'name="kind" value="(\w+)" class="btn btn-primary" data-nd-busy', corpo)
            conferir(f'{nome}: o botão principal abre o seguimento sugerido',
                     principal is not None and principal.group(1) == 'seguimento', principal and principal.group(1))
        if secretaria:
            corpo = cliente_de(secretaria).get(reverse('patients:detail', args=[p4.id])).content.decode()
            conferir('a secretária não vê o botão', 'nd-novo-atendimento' not in corpo)
        lista = c.get(reverse('patients:detail', args=[p2.id])).content.decode()
        conferir('a ficha diz qual estruturada é', 'Estruturada · seguimento' in lista and 'Estruturada · 1ª consulta' in lista)
        linha = c.get(reverse('clinical:timeline', args=[p2.id])).content.decode()
        conferir('o prontuário diz o tipo', 'Seguimento e retorno' in linha and 'Primeira consulta' in linha)

        print('\n8. Escalas no texto livre')
        p6 = novo_paciente()
        livre = atendimento(p6, kind=EncounterKind.FREE_TEXT, free_text='Retorno.')
        html = c.get(reverse('clinical:detail', args=[livre.id])).content.decode()
        conferir('o cartão das escalas', 'id="escalas"' in html and 'scale-picker' in html and 'Escalas funcionais' in html)
        conferir('o script do seletor', 'clinical/exam.js' in html)
        conferir('o formulário salva o texto antes', 'nd-scale-form' in html
                 and re.search(r'class="nd-scale-form"[^>]*data-nd-save-encounter-before-submit', html) is not None)
        conferir('continua sem o roteiro de exame', 'tab-exame' not in html)
        escala = (ExamScale.objects.filter(tenant=tenant, active=True)
                  .prefetch_related('items').order_by('code').first())
        conferir('há escala cadastrada para aplicar', escala is not None)
        if escala is not None:
            corpo = {f'escala__{escala.code}__{i.code}': str(i.options[0]['value']) for i in escala.items.all()}
            r = c.post(reverse('clinical:record-scale', args=[livre.id, escala.code]), corpo)
            conferir('gravar volta para #escalas', r.headers.get('Location', '').endswith('#escalas'), r.headers.get('Location'))
            achado = ExaminationFinding.objects.filter(encounter=livre, item_code=f'escala.{escala.code}').first()
            conferir('a escala é um achado do atendimento', achado is not None and achado.numeric_value is not None)
            from clinical.series import _escalas

            serie = _escalas(SimpleNamespace(tenant_id=tenant.id), p6).get(f'escala:{escala.code}')
            conferir('e entra na série do gráfico de evolução', serie is not None and len(serie['pontos']) == 1)
            estruturado = atendimento(p6)
            r = c.post(reverse('clinical:record-scale', args=[estruturado.id, escala.code]), corpo)
            conferir('no estruturado volta para a aba do exame', r.headers.get('Location', '').endswith('#tab-exame'))
            serie = _escalas(SimpleNamespace(tenant_id=tenant.id), p6).get(f'escala:{escala.code}')
            conferir('os dois tipos na mesma série', serie is not None and len(serie['pontos']) == 2)
            fechar(livre)
            r = c.post(reverse('clinical:record-scale', args=[livre.id, escala.code]), {})
            conferir('finalizado não regrava', ExaminationFinding.objects.filter(
                encounter=livre, item_code=f'escala.{escala.code}').exists())

        print('\n9. O resto do sistema lê a evolução')
        from ai import chat_prompt, services as ai_services
        from ai.context import AIAuthorization
        from ai.tools import clinical as ferramentas
        from reporting.acervo import atendimentos_rows

        aut = AIAuthorization(tenant_id=tenant.id, user_id=medico.id, membership_id=vinculo.id,
                              patient_id=p2.id, encounter_id=fechado.id)
        linhas = ferramentas.get_patient_timeline(aut, limit=5)
        conferir('a linha do tempo da IA traz a evolução',
                 any(l.get('evolucao') == 'Sem tremor desde o ajuste.' for l in linhas))
        contexto_chat = chat_prompt.build_patient_context(aut)
        conferir('o chat a lê', 'Evolução: Sem tremor desde o ajuste.' in contexto_chat)
        apoio, _ = ai_services._gather_diagnostic_context(aut, fechado)
        conferir('o apoio diagnóstico a lê',
                 apoio['atendimento_atual'].get('evolucao_desde_a_ultima_consulta') == 'Sem tremor desde o ajuste.')
        linha = next((x for x in atendimentos_rows(tenant.id) if x['id'] == str(fechado.id)), None)
        conferir('a exportação tem a seção Evolução', linha is not None and linha.get('Evolução') == 'Sem tremor desde o ajuste.')
        conferir('e o tipo legível', linha is not None and linha.get('tipo') == 'Seguimento e retorno')
        conferir('o texto livre exporta como Texto livre', linha is not None and 'Texto livre' in linha)
        resumo = c.get(reverse('clinical:summary', args=[fechado.id])).content.decode()
        conferir('o resumo impresso mostra a evolução', '<h2>Evolução</h2>' in resumo and 'Sem tremor' in resumo)
        conferir('e não imprime queixa vazia', 'Queixa principal' not in resumo)
        depois = atendimento(p2, estrutura=EstruturaDoAtendimento.SEGUIMENTO)
        anterior = selectors.consulta_anterior(SimpleNamespace(tenant_id=tenant.id), depois)
        conferir('a consulta anterior é o seguimento fechado', anterior is not None and anterior.id == fechado.id)
        gaveta = c.get(reverse('clinical:detail', args=[depois.id])).content.decode()
        conferir('a gaveta mostra a evolução dele', 'Sem tremor desde o ajuste.' in gaveta)
        rascunho = atendimento(p2, estrutura=EstruturaDoAtendimento.SEGUIMENTO, evolucao='Algo.')
        conferir('descartar vê a evolução como conteúdo', finalization.has_content(rascunho))

        print('\n10. O código do segundo fator em casas')
        from accounts.forms import MFAChallengeForm

        campo = str(MFAChallengeForm()['code'])
        conferir('entrar/reconfirmar: seis casas', 'data-nd-otp="6"' in campo)
        conferir('com o código de recuperação', 'data-nd-otp-recuperacao' in campo)
        conferir('e o nome de sempre', 'name="code"' in campo and 'autocomplete="one-time-code"' in campo)
        raiz = Path(dj_settings.BASE_DIR)
        conferir('configurar o MFA: casas', 'data-nd-otp="6"' in (raiz / 'templates/accounts/mfa_setup.html').read_text(encoding='utf-8'))
        equipe = (raiz / 'templates/tenancy/team.html').read_text(encoding='utf-8')
        conferir('reset da equipe: casas compactas', 'data-nd-otp="6" data-nd-otp-compacto' in equipe)
        for molde in ('base.html', 'base_auth.html'):
            conferir(f'{molde} carrega o script',
                     'duralux/nd-otp.js' in (raiz / 'templates' / molde).read_text(encoding='utf-8'))
        script = (raiz / 'static/duralux/nd-otp.js').read_text(encoding='utf-8')
        conferir('o script mantém o campo e só desenha', 'nd-otp__campo' in script and 'aria-hidden' in script)
        css = (raiz / 'static/duralux/neurodoc.css').read_text(encoding='utf-8')
        conferir('o campo transparente em 16px (sem zoom no iPhone)',
                 re.search(r'\.nd-otp__campo \{[^}]*font-size: 16px', css) is not None)
        login = Client().get(reverse('accounts:login'))
        conferir('a tela de entrar continua abrindo', login.status_code == 200)

        raise _Desfaz
except _Desfaz:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} item(ns)')
    for f in falhas:
        print('  -', f)
    raise SystemExit(1)
print('OK: primeira consulta, seguimento, escalas no texto livre e o código em casas.')
