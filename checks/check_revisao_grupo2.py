"""O restante da revisão de 2026-11-02 (1.33) e os três pedidos de 2026-11-03.

Tenta quebrar cada item:

- **S5** segundo fator obrigatório para dono e médico: aviso antes do prazo,
  configuração pedida depois dele, secretária livre, a exportação do acervo
  pedindo o código, e `desligado` desligando;
- **S6** ações graves do console pedindo o código de novo; desligar, não;
- **S8/C5** a recusa do documento repetido sem dizer "é cliente", o limite
  de tentativas de cadastro, e o selo do responsável sem e-mail confirmado;
- **C6** conta existente com e-mail descartável vai para "faça login", e o
  convite antigo para descartável explica em vez de levar a um beco;
- **S2-b/T11** emitir em papel e escrever a indicação clínica exigem o CRM
  validado;
- **W6** consulta da lista de espera trocada de paciente devolve a espera
  ao topo; cancelada, só com a caixa marcada;
- **T9/T13** convênio fora da vigência recusado ao escolher, e desfeito ao
  remarcar para fora dela;
- **T12, T8, W8, W10, W11, C9** e o `failure` da trilha;
- **2026-11-03** a nota do médico na tabela de hipóteses, o tipo da consulta
  na grade e o mais recente no topo.

Tudo numa transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_revisao_grupo2.py
"""
import uuid
from datetime import date, timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import mfa
from accounts.models import PhysicianProfile, User
from audit.models import AuditEvent, AuditOutcome
from clinical.models import Encounter, EncounterDiagnosis, EncounterKind, EncounterStatus
from patients.models import HealthPlan, Insurer, Patient, PatientCoverage, RegistrationStage
from scheduling import espera, services
from scheduling.models import AppointmentType, BillingMode, EsperaStatus
from tenancy.context import AccessContext
from tenancy.invitations import issue_invitation
from tenancy.models import InvitationPurpose, Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PlanCode

mail.outbox = []
falhas = []
SENHA = 'S3nhaF0rteDeVerdade!2026'


def conferir(nome, ok, detalhe=''):
    print(f'  [{"ok" if ok else "FALHA"}] {nome}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(nome)


def cliente_de(vinculo):
    c = Client()
    c.force_login(vinculo.user)
    s = c.session
    s['tenant_id'] = str(vinculo.tenant_id)
    s.save()
    return c


def console(su, recente=True):
    s = Client()
    s.force_login(su)
    requisicao = type('R', (), {'session': s.session, 'user': su})()
    otp_login(requisicao, TOTPDevice.objects.filter(user=su, confirmed=True).first())
    if recente:
        mfa.mark_recent_mfa(requisicao)
    else:
        requisicao.session[mfa.RECENT_MFA_SESSION_KEY] = (timezone.now() - timedelta(hours=1)).isoformat()
    requisicao.session.save()
    s.cookies['sessionid'] = requisicao.session.session_key
    return s


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.get(tenant=clinica, user__email='doctor-a@demo.neurodoc.local')
dono = Membership.objects.filter(tenant=clinica, roles__contains=[Role.OWNER], status=MembershipStatus.ACTIVE).first()
secretaria = Membership.objects.filter(tenant=clinica, roles__contains=[Role.SECRETARY], status=MembershipStatus.ACTIVE).first()
ctx = AccessContext(user_id=medico.user_id, tenant_id=clinica.id, membership_id=medico.id,
                    permissions=frozenset(medico.roles), request_id=uuid.uuid4())

try:
    with transaction.atomic():
        TOTPDevice.objects.filter(user__in=[dono.user, medico.user, secretaria.user]).delete()

        print('=== S5. Segundo fator obrigatório ===')
        with override_settings(SEGUNDO_FATOR_OBRIGATORIO_DESDE='desligado'):
            conferir('desligado não pede nada', mfa.prazo_do_segundo_fator() is None
                     and not mfa.segundo_fator_pendente(dono.user, dono.roles))
            r = cliente_de(dono).get('/app/reporting/')
            conferir('desligado: o dono entra', r.status_code == 200)
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        with override_settings(SEGUNDO_FATOR_OBRIGATORIO_DESDE=amanha):
            r = cliente_de(dono).get('/app/reporting/')
            conferir('antes do prazo: entra, com o aviso', r.status_code == 200
                     and 'data-nd-aviso="segundo-fator"' in r.content.decode())
            r = cliente_de(secretaria).get('/app/reporting/')
            conferir('a secretária não vê o aviso', 'data-nd-aviso="segundo-fator"' not in r.content.decode())
        hoje = timezone.localdate().isoformat()
        with override_settings(SEGUNDO_FATOR_OBRIGATORIO_DESDE=hoje):
            r = cliente_de(dono).get('/app/patients/')
            conferir('no prazo: o dono vai à configuração', r.status_code == 302
                     and '/accounts/mfa/setup/' in r['Location'] and 'obrigatorio=1' in r['Location'], r.get('Location'))
            r = cliente_de(medico).get('/app/patients/')
            conferir('o médico também', r.status_code == 302 and '/accounts/mfa/setup/' in r['Location'])
            r = cliente_de(secretaria).get('/app/patients/')
            conferir('a secretária segue entrando', r.status_code == 200, r.status_code)
            r = cliente_de(dono).post('/app/patients/', {})
            conferir('POST volta ao painel, não à rota do POST', r.status_code == 302 and 'next=%2Fapp%2Freporting%2F' in r['Location'])
            r = cliente_de(dono).get('/accounts/mfa/setup/?obrigatorio=1')
            conferir('a configuração abre e explica', r.status_code == 200 and 'é obrigatório' in r.content.decode())
            TOTPDevice.objects.create(user=dono.user, name='roteiro', confirmed=True)
            r = cliente_de(dono).get('/app/patients/')
            conferir('com o dispositivo, entra', r.status_code == 200, r.status_code)
        TOTPDevice.objects.filter(user=dono.user).delete()
        c = cliente_de(dono)
        r = c.post('/app/reporting/acervo/', {'acervo': 'acervo_pacientes', 'formato': 'json'})
        conferir('exportar sem dispositivo leva à configuração', r.status_code == 302 and 'mfa/setup' in r['Location'])
        TOTPDevice.objects.create(user=dono.user, name='roteiro', confirmed=True)
        r = c.post('/app/reporting/acervo/', {'acervo': 'acervo_pacientes', 'formato': 'json'})
        conferir('exportar sem código recente pede o código', r.status_code == 302 and 'mfa/confirmar' in r['Location'], r.get('Location'))
        s = c.session
        s[mfa.RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
        s.save()
        r = c.post('/app/reporting/acervo/', {'acervo': 'acervo_pacientes', 'formato': 'json'})
        conferir('com o código recente, exporta', r.status_code == 302 and '/app/reporting/' in r['Location']
                 and 'mfa' not in r['Location'], r.get('Location'))

        print('=== S6. Ações graves do console ===')
        su = User.objects.create_superuser(email='su-roteiro-grupo2@example.invalid', password=None,
                                           email_verified_at=timezone.now())
        TOTPDevice.objects.create(user=su, name='roteiro-grupo2', confirmed=True)
        alvo = Tenant.objects.create(legal_name='CLINICA ROTEIRO GRUPO DOIS', cnpj='19131243000197',
                                     slug='roteiro-grupo2', plan=PlanCode.FREE)
        r = console(su, recente=False).post(f'/instalacao/organizacoes/{alvo.id}/estado/',
                                            {'status': 'closed', 'status_note': 'roteiro'})
        alvo.refresh_from_db()
        conferir('encerrar sem código recente pede o código', r.status_code == 302
                 and 'mfa/confirmar' in r['Location'] and alvo.status == 'active', r.get('Location'))
        console(su).post(f'/instalacao/organizacoes/{alvo.id}/estado/', {'status': 'closed', 'status_note': 'roteiro'})
        alvo.refresh_from_db()
        conferir('com código recente, encerra', alvo.status == 'closed')
        r = console(su, recente=False).post('/instalacao/operacao/tiss/', {'acao': 'desligar'})
        conferir('desligar continua um clique', r.status_code == 302 and 'mfa' not in r['Location'], r.get('Location'))

        print('=== S8, C5, C6. Cadastro ===')
        from base.forms import MENSAGEM_DOCUMENTO_EM_USO, OrganizationSignupForm
        f = OrganizationSignupForm(data={'documento': clinica.cnpj or clinica.cpf})
        f.is_valid()
        conferir('documento repetido: recusa sem dizer "já está cadastrado"',
                 MENSAGEM_DOCUMENTO_EM_USO in str(f.errors.get('documento')) and 'cadastrad' not in str(f.errors.get('documento')))
        cache.clear()
        _, tk = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
        codigos = [Client(REMOTE_ADDR='203.0.113.77').post(f'/signup/{tk}/', {}).status_code for _ in range(21)]
        conferir('a 21ª tentativa de cadastro na hora é recusada', codigos[-1] == 429 and 429 not in codigos[:20], codigos[-3:])
        cache.clear()
        velha = User.objects.create_user(email='antiga@mailinator.com', password=SENHA)
        from catalogs.models import DominioDescartavel
        DominioDescartavel.objects.get_or_create(dominio='mailinator.com')
        f = OrganizationSignupForm(data={'email': 'antiga@mailinator.com'})
        f.is_valid()
        conferir('conta existente com descartável não recebe a recusa de descartável', 'email' not in f.errors, f.errors.get('email'))
        inv, tk2 = issue_invitation(purpose=InvitationPurpose.COLLABORATOR, target_tenant=clinica,
                                    email_binding='novo@mailinator.com', role_grants=[Role.SECRETARY])
        r = Client().get(reverse('tenancy:accept-invite', args=[tk2]))
        conferir('convite antigo para descartável explica o caminho', r.status_code == 200
                 and 'Peça a quem convidou um convite novo' in r.content.decode(), r.status_code)
        sem = Tenant.objects.create(legal_name='SEM CONFIRMAR', cnpj='', cpf='52998224725', slug='roteiro-sem-confirmar', plan=PlanCode.FREE)
        u = User.objects.create_user(email='semconfirmar@example.invalid', password=SENHA)
        Membership.objects.create(tenant=sem, user=u, roles=[Role.OWNER], status=MembershipStatus.ACTIVE, activated_at=timezone.now())
        pagina = console(su).get('/instalacao/organizacoes/').content.decode()
        conferir('o console marca o responsável sem e-mail confirmado', 'e-mail não confirmado' in pagina)

        print('=== S2-b, T11. CRM validado ===')
        perfil = PhysicianProfile.objects.get(user=medico.user)
        PhysicianProfile.objects.filter(id=perfil.id).update(verification_status='pending')
        pac = Patient.objects.create(tenant=clinica, full_name='PACIENTE ROTEIRO GRUPO DOIS',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        from documents import issuance
        from documents.models import MedicalDocument, MedicalDocumentKind
        from documents.pdf.prescription import SIMPLE
        doc = issuance.create_draft(clinica, pac, None, medico, medico.user_id, MedicalDocumentKind.PRESCRIPTION,
                                    {'prescription_text': 'Dipirona', 'special_instructions': '', 'prescription_format': SIMPLE})
        r = cliente_de(medico).post(reverse('documents:medical-issue-paper', args=[doc.id]))
        doc.refresh_from_db()
        conferir('CRM pendente: emitir em papel é recusado', r.status_code == 404 and not doc.document_number, r.status_code)
        MedicalDocument.objects.filter(id=doc.id).update(status='ready_to_sign')
        r = cliente_de(medico).get(reverse('documents:medical-detail', args=[doc.id]))
        conferir('e a tela diz por quê, no lugar do botão', 'Emitir exige o CRM validado' in r.content.decode()
                 and 'Emitir para assinar e carimbar' not in r.content.decode())
        from tiss import guias as tiss_guias
        from tenancy.context import build_access_context
        from tenancy.permissions import Capability, capabilities_for
        caps = capabilities_for(medico.roles, clinically_enabled=False, ai_contracted=True, tiss_contracted=True)
        ctx_pend = AccessContext(user_id=medico.user_id, tenant_id=clinica.id, membership_id=medico.id,
                                 permissions=frozenset(medico.roles), request_id=None, capabilities=caps)
        try:
            tiss_guias.registrar_indicacao(ctx_pend, medico.user, type('G', (), {})(), 'texto')
            conferir('CRM pendente: indicação clínica recusada', False)
        except tiss_guias.GuiaRecusada:
            conferir('CRM pendente: indicação clínica recusada', True)
        PhysicianProfile.objects.filter(id=perfil.id).update(verification_status='verified')
        r = cliente_de(medico).post(reverse('documents:medical-issue-paper', args=[doc.id]))
        doc.refresh_from_db()
        conferir('validado: emite em papel', bool(doc.document_number), r.status_code)

        print('=== W6. Lista de espera ===')
        pac2 = Patient.objects.create(tenant=clinica, full_name='PACIENTE ROTEIRO OUTRO',
                                      registration_stage=RegistrationStage.COMPLETE,
                                      birth_date_unknown_reason='Roteiro de verificação.')
        inicio = timezone.now().replace(microsecond=0) + timedelta(days=9, hours=3)
        appt = services.reserve_appointment(ctx, pac, medico, inicio, inicio + timedelta(minutes=30),
                                            AppointmentType.OTHER, is_overbook=True,
                                            override_reason='roteiro', override_by=medico)
        e = espera.incluir(ctx, pac)
        espera.marcar_agendada(ctx, e, appt)
        services.change_appointment_patient(ctx, appt, pac2, 'roteiro', medico.user_id)
        devolvida = espera.devolver_a_lista(ctx, appt)
        e.refresh_from_db()
        conferir('trocado o paciente, a espera volta ao topo', devolvida is not None and e.status == EsperaStatus.AGUARDANDO
                 and e.posicao == 1 and e.appointment_id is None, (e.status, e.posicao))
        conferir('e não volta duas vezes', espera.devolver_a_lista(ctx, appt) is None)
        espera.retirar(ctx, e, motivo='roteiro')
        appt2 = services.reserve_appointment(ctx, pac, medico, inicio + timedelta(hours=2),
                                             inicio + timedelta(hours=2, minutes=30), AppointmentType.OTHER,
                                             is_overbook=True, override_reason='roteiro', override_by=medico)
        c = cliente_de(secretaria)
        dia = timezone.localtime(appt2.starts_at).date()
        c.post(reverse('scheduling:action', args=[appt2.id, 'cancel']), {'reason': 'roteiro'})
        appt2.refresh_from_db()
        conferir('o cancelamento passou', appt2.status == 'cancelled', appt2.status)
        conferir('cancelar sem a caixa não põe na lista', not espera.esperando(clinica.id, pac.id))

        print('=== T9/T13. Vigência do convênio ===')
        operadora = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO GRUPO DOIS', ans_registration='368253')
        plano = HealthPlan.objects.create(tenant=clinica, insurer=operadora, name='PLANO ROTEIRO')
        venc = PatientCoverage.objects.create(tenant=clinica, patient=pac2, plan=plano, member_number='1',
                                              starts_on=date(2020, 1, 1), ends_on=timezone.localdate() - timedelta(days=1))
        try:
            services.set_billing_mode(ctx, appt, BillingMode.INSURANCE, venc.id, medico.user_id)
            conferir('convênio vencido recusado ao escolher', False)
        except services.SchedulingError as exc:
            conferir('convênio vencido recusado ao escolher', 'vigente' in str(exc))
        ate = timezone.localtime(appt.starts_at).date()
        cob = PatientCoverage.objects.create(tenant=clinica, patient=pac2, plan=plano, member_number='2',
                                             starts_on=date(2020, 1, 1), ends_on=ate)
        services.set_billing_mode(ctx, appt, BillingMode.INSURANCE, cob.id, medico.user_id)
        appt.refresh_from_db()
        novo = appt.starts_at + timedelta(days=2)
        remarcado = services.reschedule_appointment(ctx, appt, novo, novo + timedelta(minutes=30), medico.user_id)
        conferir('remarcar para fora da vigência desfaz a escolha', remarcado.billing_mode == ''
                 and remarcado.coverage_id is None and remarcado.forma_de_cobranca_desfeita)

        print('=== T12. Exame realizado ===')
        from finance.models import Receivable
        restr = [c for c in Receivable._meta.constraints if c.name == 'finance_receivable_reserva_uniq'][0]
        conferir('uma cobrança viva por reserva (a cancelada fica de fora)', "('status', 'cancelled')" in str(restr.condition))
        fonte = open('agenda_exames/services.py', encoding='utf-8').read()
        conferir('a troca depois da realização recusa pagamento, ajuste e guia',
                 '_trocar_cobranca_do_realizado' in fonte and 'payments.exists()' in fonte and 'adjustments.exists()' in fonte)

        print('=== T8, W8, W10, W11, C9 e a trilha ===')
        fonte = open('tiss/views_guia.py', encoding='utf-8').read()
        conferir('a guia é gravada travada e só nos campos do formulário',
                 'guias._travar_rascunho(guia)' in fonte and 'update_fields=sorted(set(campos)' in fonte)
        from reporting.patients import returning_patients_count
        inicio_p = timezone.localdate() - timedelta(days=3650)
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as q:
            returning_patients_count(clinica, inicio_p, timezone.localdate())
        conferir('retornos do período numa consulta só', len(q.captured_queries) == 1, len(q.captured_queries))
        fonte = open('scheduling/views.py', encoding='utf-8').read()
        conferir('a espera do médico que saiu mantém o médico ao editar',
                 'escolhido == entrada.physician_membership_id' in fonte)
        fonte = open('patients/views.py', encoding='utf-8').read()
        conferir('a ficha não lê o texto dos atendimentos', ".defer(\n            'chief_complaint'" in fonte)
        fonte = open('catalogs/descartaveis.py', encoding='utf-8').read()
        conferir('a queda da lista é medida contra o que está gravado', 'DominioDescartavel.objects.count())' in fonte)
        conferir('`failure` é um desfecho conhecido da trilha', 'failure' in dict(AuditOutcome.choices))

        print('=== 2026-11-03. Hipóteses e grade de atendimentos ===')
        enc = Encounter.objects.create(tenant=clinica, patient=pac2, physician_membership=medico, appointment=appt,
                                       occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
                                       status=EncounterStatus.IN_PROGRESS, free_text='roteiro')
        EncounterDiagnosis.objects.create(tenant=clinica, encounter=enc, rank=1, code_snapshot='G61',
                                          description_snapshot='Polineuropatia', certainty='confirmed',
                                          physician_note='NOTA DO MEDICO ROTEIRO')
        velho = Encounter.objects.create(tenant=clinica, patient=pac2, physician_membership=medico,
                                         occurred_at=timezone.now() - timedelta(days=400), kind=EncounterKind.FREE_TEXT,
                                         status=EncounterStatus.IN_PROGRESS, free_text='antigo')
        r = cliente_de(medico).get(reverse('clinical:detail', args=[enc.id]))
        conferir('a nota do médico aparece na tabela de hipóteses', 'NOTA DO MEDICO ROTEIRO' in r.content.decode())
        def grade(url):
            # Só a tabela de atendimentos: a data de hoje aparece em outros
            # pontos da ficha, e a busca na página inteira acertava por sorte.
            pagina = cliente_de(medico).get(url).content.decode()
            inicio = pagina.find('id="atendimentos"')
            return pagina[inicio:pagina.find('</table>', inicio)]

        def linha(html, quando):
            return html.find(timezone.localtime(quando).strftime('%d/%m/%Y %H:%M'))

        html = grade(reverse('patients:detail', args=[pac2.id]))
        conferir('a grade tem a coluna Consulta com o tipo', '>Consulta</th>' in html and 'Outro' in html)
        conferir('o mais recente vem primeiro', -1 < linha(html, enc.occurred_at) < linha(html, velho.occurred_at),
                 (linha(html, enc.occurred_at), linha(html, velho.occurred_at)))
        html = grade(reverse('patients:detail', args=[pac2.id]) + '?ordenar=abertura&desc=0')
        conferir('a seta inverte (desc=0)', -1 < linha(html, velho.occurred_at) < linha(html, enc.occurred_at),
                 (linha(html, velho.occurred_at), linha(html, enc.occurred_at)))
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Restante da revisão e pedidos de 2026-11-03: tudo confere.')
