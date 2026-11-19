"""Dashboard: perfil da carteira por clínica e por médico, CSV e mailing.

O que este roteiro tenta quebrar (`reporting/painel.py`, `PainelView`,
`MailingView`):

- **quem abre**: responsável, gestor e médico sim; secretaria em 404 e sem
  o item no menu;
- **a clínica**: nada da clínica B aparece nos números da A;
- **o médico**: quem só atende vê a própria carteira, e o `?medico=` de um
  colega é ignorado; quem administra escolhe qualquer médico da clínica, e
  o id de um médico de outra clínica não vale;
- **os números**: faixas etárias e mediana na data final, sexo, UF, a
  regra das células pequenas no município, origem, convênio vigente, novos
  contra antigos, o mês de Brasília;
- **o CID**: a última palavra por paciente e código (suspeita refutada não
  conta; suspeita confirmada vira só confirmada), confirmados e suspeitas
  separados, e o responsável que não é médico sem a série nem o CSV;
- **o CSV**: cada seção, com BOM, sem fórmula executável, na trilha sem
  número; seção desconhecida e data ilegível sem erro 500;
- **o mailing**: só quem consentiu e não revogou, com paciente ativo e
  contato válido; um endereço uma vez; o link de descadastro; nada do
  paciente; o escopo do médico; só o responsável, só com a declaração e
  com o código recente; e a porta antiga dos Indicadores sem deixá-lo sair.

Tudo numa transação desfeita no fim.
"""
import csv
import datetime
import io
import uuid

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import mfa
from accounts.models import User
from audit.models import AuditEvent
from clinical.models import DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus
from patients.models import (
    HealthPlan, Insurer, Patient, PatientContact, PatientCoverage, PatientStatus, ReferralSource,
    RegistrationStage, SexAtRegistration,
)
from reporting import painel
from reporting.models import ReportExport
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.context import AccessContext
from tenancy.permissions import capabilities_for
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []
CHR = chr(10)
SENHA = 'Senha-forte-123!'
hoje = timezone.localdate()


def conferir(rotulo, condicao, detalhe=''):
    print(f'  {"ok " if condicao else "FALHA"}  {rotulo}' + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


def nova_clinica(nome):
    return Tenant.objects.create(
        legal_name=nome, slug=f'painel-{uuid.uuid4().hex[:10]}', cpf=str(uuid.uuid4().int)[:11],
    )


def nova_pessoa(rotulo, tenant, papeis):
    user = User.objects.create_user(
        email=f'{rotulo}-{uuid.uuid4().hex[:6]}@example.com', password=SENHA,
        first_name=rotulo.capitalize(),
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=['email_verified_at'])
    TOTPDevice.objects.create(user=user, confirmed=True, name='roteiro')
    vinculo = Membership.objects.create(
        tenant=tenant, user=user, roles=papeis, status=MembershipStatus.ACTIVE, activated_at=timezone.now(),
    )
    return user, vinculo


def paciente(tenant, nome, *, nascimento=None, sexo='', uf='', cidade='', origem='', status=PatientStatus.ACTIVE):
    return Patient.objects.create(
        tenant=tenant, full_name=nome, birth_date=nascimento,
        birth_date_unknown_reason='' if nascimento else 'Roteiro de verificação.',
        sex_at_registration=sexo or SexAtRegistration.NOT_INFORMED,
        state=uf, city=cidade, referral_source=origem or ReferralSource.NOT_INFORMED,
        status=status, registration_stage=RegistrationStage.COMPLETE,
    )


def atendimento(tenant, pac, vinculo, dias_atras, cids=()):
    enc = Encounter.objects.create(
        tenant=tenant, patient=pac, physician_membership=vinculo,
        occurred_at=timezone.now() - datetime.timedelta(days=dias_atras),
        status=EncounterStatus.FINALIZED, kind=EncounterKind.FREE_TEXT, free_text='Roteiro do Dashboard.',
    )
    for codigo, certeza in cids:
        EncounterDiagnosis.objects.create(
            tenant=tenant, encounter=enc, code_snapshot=codigo, description_snapshot=f'Descrição {codigo}',
            certainty=certeza, rank=1,
        )
    return enc


def na_clinica(client, user, tenant, *, mfa_recente=False):
    client.force_login(user)
    sessao = client.session
    sessao['tenant_id'] = str(tenant.id)
    if mfa_recente:
        sessao[mfa.RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    sessao.save()


def escopo_de(vinculo, **params):
    """O escopo como a view o monta, com o contexto que o middleware montaria."""
    ctx = AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(vinculo.roles, clinically_enabled=True, ai_contracted=False),
    )
    return painel.resolver_escopo(ctx, params)


def linhas(dados):
    return {l['rotulo']: l['n'] for l in dados}


def csv_de(resposta):
    texto = resposta.content.decode('utf-8')
    return texto, list(csv.reader(io.StringIO(texto.lstrip('﻿'))))


try:
    with transaction.atomic():
        A = nova_clinica('Clínica A do Dashboard')
        B = nova_clinica('Clínica B do Dashboard')
        dona, v_dona = nova_pessoa('dona', A, [Role.OWNER])
        gestor, v_gestor = nova_pessoa('gestor', A, [Role.MANAGER])
        medico, v_medico = nova_pessoa('medico', A, [Role.DOCTOR])
        colega, v_colega = nova_pessoa('colega', A, [Role.DOCTOR])
        secretaria, v_secretaria = nova_pessoa('secretaria', A, [Role.SECRETARY])
        dono_b, v_dono_b = nova_pessoa('donob', B, [Role.OWNER, Role.DOCTOR])

        # ---- carteira: 6 pacientes do médico em Campinas, 1 em Itu, 2 do colega
        ref = hoje
        pacientes_med = []
        for i, (idade, sexo) in enumerate([(10, 'female'), (25, 'male'), (35, 'female'), (45, 'female'), (65, 'male'), (85, 'female')]):
            nasc = ref.replace(year=ref.year - idade) - datetime.timedelta(days=1)
            p = paciente(A, f'Paciente M{i}', nascimento=nasc, sexo=sexo, uf='SP', cidade='campinas',
                         origem=ReferralSource.INTERNET if i < 4 else ReferralSource.PHYSICIAN)
            pacientes_med.append(p)
        itu = paciente(A, 'Paciente Itu', uf='SP', cidade='=HYPERLINK("x")', origem=ReferralSource.PATIENT)
        pacientes_med.append(itu)
        pac_col1 = paciente(A, 'Paciente C1', uf='RJ', cidade='Niterói')
        pac_col2 = paciente(A, 'Paciente C2', uf='RJ', cidade='Niterói')
        arquivado = paciente(A, 'Paciente Arquivado', uf='SP', cidade='campinas', status=PatientStatus.ARCHIVED)
        marcado = paciente(A, 'Paciente Marcado', uf='MG', cidade='BH')
        pac_b = paciente(B, 'Paciente da B', uf='SP', cidade='campinas')

        # atendimentos do médico: antigo (fora do período) para M0, novos para os demais
        atendimento(A, pacientes_med[0], v_medico, 500)
        atendimento(A, pacientes_med[0], v_medico, 10, cids=[('G40', DiagnosisCertainty.CONFIRMED)])
        atendimento(A, pacientes_med[1], v_medico, 40, cids=[('G35', DiagnosisCertainty.SUSPECTED)])
        atendimento(A, pacientes_med[1], v_medico, 20, cids=[('G35', DiagnosisCertainty.REFUTED)])
        atendimento(A, pacientes_med[2], v_medico, 30, cids=[('G20', DiagnosisCertainty.SUSPECTED)])
        atendimento(A, pacientes_med[2], v_medico, 5, cids=[('G20', DiagnosisCertainty.CONFIRMED)])
        atendimento(A, pacientes_med[3], v_medico, 15, cids=[('G43', DiagnosisCertainty.SUSPECTED)])
        for p in pacientes_med[4:]:
            atendimento(A, p, v_medico, 3)
        atendimento(A, pac_col1, v_colega, 8, cids=[('F32', DiagnosisCertainty.CONFIRMED)])
        atendimento(A, pac_col2, v_colega, 8)
        atendimento(A, arquivado, v_medico, 8)
        atendimento(B, pac_b, v_dono_b, 8, cids=[('G40', DiagnosisCertainty.CONFIRMED)])
        inicio_marcado = timezone.now() + datetime.timedelta(days=3)
        fim_marcado = inicio_marcado + datetime.timedelta(minutes=30)
        Appointment.objects.create(
            tenant=A, patient=marcado, physician_membership=v_medico, starts_at=inicio_marcado,
            ends_at=fim_marcado, occupied_range=(inicio_marcado, fim_marcado),
            status=AppointmentStatus.SCHEDULED, type=AppointmentType.FIRST_VISIT,
        )

        # convênio: vigente para M0, vencido para M1
        operadora = Insurer.objects.create(tenant=A, name='Operadora Roteiro')
        plano = HealthPlan.objects.create(tenant=A, insurer=operadora, name='Plano Ouro')
        PatientCoverage.objects.create(tenant=A, patient=pacientes_med[0], plan=plano)
        PatientCoverage.objects.create(tenant=A, patient=pacientes_med[1], plan=plano,
                                       ends_on=hoje - datetime.timedelta(days=1))

        # contatos para o mailing
        agora = timezone.now()

        def contato(pac, email, **extra):
            return PatientContact.objects.create(
                tenant=pac.tenant, patient=pac, name=f'Contato {pac.full_name}', relationship='self',
                email=email, phone='', **extra,
            )
        consentiu = dict(marketing_opt_in_at=agora, marketing_opt_in_evidence='roteiro do Dashboard')
        c_ok = contato(pacientes_med[0], 'ok@example.com', **consentiu)
        contato(pacientes_med[1], 'OK@Example.com', **consentiu)  # mesmo endereço, outra caixa
        contato(pacientes_med[2], 'sem-consentimento@example.com')
        contato(pacientes_med[3], 'revogou@example.com', marketing_opt_out_at=agora, **consentiu)
        contato(pacientes_med[4], 'vencido@example.com', valid_until=agora - datetime.timedelta(days=1), **consentiu)
        contato(arquivado, 'arquivado@example.com', **consentiu)
        c_col = contato(pac_col1, 'colega@example.com', **consentiu)
        contato(pac_b, 'da-b@example.com', **consentiu)

        print(CHR + '1. Quem abre o Dashboard')
        url = reverse('reporting:painel')
        for rotulo, user, esperado in (
            ('responsável', dona, 200), ('gestor', gestor, 200), ('médico', medico, 200),
            ('secretaria', secretaria, 404),
        ):
            c = Client()
            na_clinica(c, user, A)
            r = c.get(url)
            conferir(f'{rotulo}: {esperado}', r.status_code == esperado, str(r.status_code))
        c = Client()
        na_clinica(c, secretaria, A)
        html = c.get(reverse('scheduling:desk')).content.decode()
        conferir('secretaria sem o item no menu', url not in html)
        c = Client()
        na_clinica(c, dona, A)
        html = c.get(url).content.decode()
        conferir('responsável com o item no menu', f'href="{url}"' in html)
        conferir('a página carrega o CSS e o script próprios', 'reporting/painel.css' in html and 'reporting/painel.js' in html)

        print(CHR + '2. A clínica: nada da B nos números da A')
        e = escopo_de(v_dona, periodo='12m')
        r = painel.resumo(e)
        conferir('carteira da A = 10 ativos (sem arquivado e sem a B)', r['carteira'] == 10, str(r['carteira']))
        conferir('mailing da A sem o contato da B', 'da-b@example.com' not in [l['email'] for l in painel.mailing_rows(A.id)])

        print(CHR + '3. O médico: a própria carteira; o colega não é dele para abrir')
        e = escopo_de(v_medico, periodo='12m')
        conferir('médico preso a si mesmo', e.medico.id == v_medico.id and not e.ve_clinica_inteira)
        carteira_med = painel.carteira(e).count()
        conferir('carteira do médico = 7 atendidos + 1 marcado', carteira_med == 8, str(carteira_med))
        e2 = escopo_de(v_medico, periodo='12m', medico=str(v_colega.id))
        conferir('?medico= do colega ignorado', e2.medico.id == v_medico.id and painel.carteira(e2).count() == carteira_med)
        c = Client()
        na_clinica(c, medico, A)
        html = c.get(url + f'?medico={v_colega.id}').content.decode()
        conferir('a tela do médico não oferece o colega', str(v_colega.id) not in html)
        e3 = escopo_de(v_dona, periodo='12m', medico=str(v_colega.id))
        conferir('responsável escolhe o colega', e3.medico.id == v_colega.id and painel.carteira(e3).count() == 2)
        e4 = escopo_de(v_gestor, periodo='12m', medico=str(v_colega.id))
        conferir('gestor escolhe o colega', e4.medico.id == v_colega.id)
        e5 = escopo_de(v_dona, periodo='12m', medico=str(v_dono_b.id))
        conferir('médico de outra clínica não vale', e5.medico is None)

        print(CHR + '4. Os números')
        e = escopo_de(v_medico, periodo='12m')
        faixas = linhas(painel.idade(e)['linhas'])
        conferir('faixas: 1 em cada', all(faixas[f] == 1 for f in ('0 a 17', '18 a 29', '30 a 39', '40 a 49', '60 a 69', '80 ou mais')), str(faixas))
        conferir('sem data numa linha própria (Itu e o marcado)', faixas.get('Sem data de nascimento') == 2, str(faixas))
        conferir('mediana fora dos sem data', painel.idade(e)['mediana'] == 40, str(painel.idade(e)['mediana']))
        conferir('sexo', linhas(painel.sexo(e)).get('Feminino') == 4 and linhas(painel.sexo(e)).get('Masculino') == 2)
        conferir('UF', linhas(painel.uf(e)) == {'SP': 7, 'MG': 1}, str(linhas(painel.uf(e))))
        mun = linhas(painel.municipio(e))
        conferir('Campinas com 6 aparece', mun.get('Campinas/SP') == 6, str(mun))
        outros = [k for k in mun if k.startswith('Outros municípios')]
        conferir('Itu e BH (1 cada) em "Outros"', outros and mun[outros[0]] == 2, str(mun))
        conferir('origem', linhas(painel.origem(e)).get('Internet') == 4 and linhas(painel.origem(e)).get('Médico') == 2)
        conv = linhas(painel.convenios(escopo_de(v_dona, periodo='12m')))
        conferir('convênio vencido não conta', conv == {'Operadora Roteiro — Plano Ouro': 1}, str(conv))
        r = painel.resumo(e)
        # M0 já vinha (500 dias); o arquivado conta: "novo" é atividade do período
        conferir('novos no período: M0 já vinha (500 dias)', r['novos'] == 7, str(r['novos']))
        conferir('atendimentos do médico no período (sem o de 500 dias)', r['atendimentos'] == 10, str(r['atendimentos']))
        mensal = painel.mensal(e)
        conferir('12 colunas no período padrão', len(mensal) == 12, str(len(mensal)))
        conferir('soma mensal = atendimentos do período', sum(m['atendimentos'] for m in mensal) == r['atendimentos'])
        conferir('altura relativa ao maior mês', max(m['alt_atendimentos'] for m in mensal) == 100)

        print(CHR + '5. O CID: a última palavra, separados, e só para quem lê prontuário')
        d = painel.diagnosticos(escopo_de(v_medico, periodo='12m'))
        conf = {l['codigo']: l['n'] for l in d['confirmados']}
        susp = {l['codigo']: l['n'] for l in d['suspeitos']}
        conferir('G40 e G20 confirmados', conf == {'G40': 1, 'G20': 1}, str(conf))
        conferir('G35 refutado depois não conta; G20 confirmado não fica em suspeita', susp == {'G43': 1}, str(susp))
        conferir('o F32 do colega fora da carteira do médico', 'F32' not in conf)
        conferir('responsável que não é médico: sem a série', painel.diagnosticos(escopo_de(v_dona)) is None)
        c = Client()
        na_clinica(c, dona, A)
        conferir('responsável que não é médico: CSV do CID em 404', c.get(url + '?baixar=cid').status_code == 404)
        html = c.get(url).content.decode()
        conferir('a tela explica por quê', 'só para quem abre prontuário' in html)
        d_b = painel.diagnosticos(escopo_de(v_dono_b))
        conferir('dono médico da B vê só a B', {l['codigo'] for l in d_b['confirmados']} == {'G40'})

        print(CHR + '6. O CSV')
        c = Client()
        na_clinica(c, medico, A)
        antes = AuditEvent.objects.filter(action='reporting.painel_csv', tenant_id=A.id).count()
        for secao in painel.SECOES_CSV:
            r = c.get(url + f'?periodo=12m&baixar={secao}')
            conferir(f'CSV {secao}', r.status_code == 200 and r['Content-Type'].startswith('text/csv'), str(r.status_code))
        r = c.get(url + '?periodo=12m&baixar=municipio')
        texto, tabela = csv_de(r)
        conferir('BOM para o Excel', texto.startswith('﻿'))
        conferir('sem paciente nem e-mail no CSV', 'Paciente' not in texto and '@' not in texto)
        r = c.get(url + '?periodo=tudo&baixar=uf')
        conferir('download privado', r['Cache-Control'] == 'private, no-store')
        depois = AuditEvent.objects.filter(action='reporting.painel_csv', tenant_id=A.id)
        conferir('cada CSV na trilha', depois.count() - antes == len(painel.SECOES_CSV) + 2)
        meta = depois.order_by('-id').first().integrity_metadata
        conferir('trilha com seção e médico, sem números', set(meta) == {'secao', 'medico', 'inicio', 'fim'}, str(meta))
        conferir('seção desconhecida: 404', c.get(url + '?baixar=__class__').status_code == 404)
        conferir('data ilegível: sem 500', c.get(url + '?inicio=2026-13-40&fim=ontem').status_code == 200)
        conferir('datas trocadas são desinvertidas', painel.periodo_da_requisicao({'inicio': '2026-05-01', 'fim': '2026-01-01'})[:2] == (datetime.date(2026, 1, 1), datetime.date(2026, 5, 1)))
        # fórmula: a cidade "=HYPERLINK" vai para "Outros" no município; o
        # CSV da UF prova a sanitização pela função de sempre
        from reporting.exporters import export_csv
        conferir('célula com "=" sai como texto', export_csv([{'a': '=1+1'}], ['a']).splitlines()[1] == "'=1+1")

        print(CHR + '7. O mailing: quem entra')
        lista = painel.mailing_rows(A.id)
        emails = sorted(l['email'].lower() for l in lista)
        conferir('só consentiu, não revogou, válido, ativo — e um endereço uma vez',
                 emails == ['colega@example.com', 'ok@example.com'], str(emails))
        conferir('colunas mínimas', list(lista[0]) == painel.MAILING_COLUNAS)
        conferir('do mesmo endereço, fica o contato mais antigo', 'ok@example.com' in [l['email'] for l in lista])
        conferir('link de descadastro de cada um', all(l['descadastro_url'].rstrip('/').split('/')[-2] == 'descadastrar' for l in lista))
        c_ok.refresh_from_db()
        conferir('o link é o do contato', c_ok.marketing_unsubscribe_token in [l['descadastro_url'] for l in lista if l['email'].lower() == 'ok@example.com'][0])
        so_colega = [l['email'] for l in painel.mailing_rows(A.id, medico=str(v_colega.id))]
        conferir('escopo do colega', so_colega == ['colega@example.com'], str(so_colega))
        conferir('médico de outra clínica: lista vazia, nunca a clínica', painel.mailing_rows(A.id, medico=str(v_dono_b.id)) == [])
        conferir('contagem igual à tela', painel.mailing_count(A.id) == painel.resumo(escopo_de(v_dona))['mailing'])

        print(CHR + '8. O mailing: quem exporta e como')
        url_m = reverse('reporting:painel-mailing')
        total = ReportExport.objects.filter(tenant_id=A.id, report_name='mailing_contatos').count
        c = Client()
        na_clinica(c, medico, A, mfa_recente=True)
        conferir('médico: 404', c.post(url_m, {'declaracao': 'sim'}).status_code == 404 and total() == 0)
        c = Client()
        na_clinica(c, gestor, A, mfa_recente=True)
        conferir('gestor: 404', c.post(url_m, {'declaracao': 'sim'}).status_code == 404 and total() == 0)
        c = Client()
        na_clinica(c, dona, A, mfa_recente=True)
        r = c.post(url_m, {})
        conferir('sem a declaração: volta, sem exportar', r.status_code == 302 and total() == 0)
        conferir('GET não exporta', c.get(url_m).status_code in (404, 405) and total() == 0)
        c2 = Client()
        na_clinica(c2, dona, A)
        r = c2.post(url_m, {'declaracao': 'sim'})
        conferir('sem o código recente: pede o código, sem exportar',
                 r.status_code == 302 and 'mfa' in r['Location'] and total() == 0, r.get('Location', ''))
        r = c.post(url_m, {'declaracao': 'sim', 'medico': str(v_colega.id)})
        exp = ReportExport.objects.filter(tenant_id=A.id, report_name='mailing_contatos').first()
        conferir('com tudo: exporta', r.status_code == 302 and exp is not None)
        conferir('declaração e médico nos parâmetros', exp.parameters == {'medico': str(v_colega.id), 'declaracao': True}, str(exp.parameters))
        conferir('uma linha (o colega)', exp.row_count == 1, str(exp.row_count))
        d = c.get(reverse('reporting:export-download', args=[exp.id]))
        conferir('download do responsável', d.status_code == 200 and b'colega@example.com' in d.content)
        c3 = Client()
        na_clinica(c3, medico, A)
        conferir('médico não baixa o arquivo', c3.get(reverse('reporting:export-download', args=[exp.id])).status_code == 404)
        c4 = Client()
        na_clinica(c4, dono_b, B, mfa_recente=True)
        conferir('outra clínica não baixa', c4.get(reverse('reporting:export-download', args=[exp.id])).status_code == 404)
        antes = total()
        r = c.post(reverse('reporting:export-request'), {
            'report_name': 'mailing_contatos', 'start': hoje.isoformat(), 'end': hoje.isoformat(),
        })
        conferir('porta dos Indicadores recusa o mailing', r.status_code == 404 and total() == antes)
        r = c.post(reverse('reporting:export-request'), {
            'report_name': 'patients_seen_detail', 'start': hoje.isoformat(), 'end': hoje.isoformat(),
        })
        conferir('e continua exportando os indicadores', r.status_code == 302)

        print(CHR + '9. A tela inteira em cada escopo, sem erro')
        for rotulo, user, params in (
            ('responsável, clínica', dona, ''), ('responsável, colega', dona, f'?medico={v_colega.id}'),
            ('médico, tudo', medico, '?periodo=tudo'), ('médico, 30 dias', medico, '?periodo=30d'),
            ('gestor, ano', gestor, '?periodo=ano'), ('dono da B', dono_b, ''),
        ):
            c = Client()
            na_clinica(c, user, B if user is dono_b else A)
            r = c.get(url + params)
            conferir(rotulo, r.status_code == 200, str(r.status_code))
        html = r.content.decode()
        conferir('a B não vê nome da A', 'Clínica A do Dashboard' not in html and 'Colega' not in html)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f in falhas:
        print(' -', f)
    raise SystemExit(1)
print('check_painel: tudo certo.')
