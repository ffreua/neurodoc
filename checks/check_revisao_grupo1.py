"""O primeiro grupo da revisão de 2026-11-02 (1.32.3): treze correções sem mudar rotina.

Tenta quebrar cada uma:

- **C4** CNPJ alfanumérico (IN RFB 2.229/2024) cadastra a clínica, com as
  letras guardadas, e não vira CPF; o numérico continua valendo;
- **C12** a declaração imprime o CNPJ pontuado;
- **S3** o teste do servidor de e-mail recusa endereço privado e local, e a
  tela não recebe o erro cru do `smtplib`;
- **S4** nome do médico e da clínica com marcação não quebram o PDF e saem
  como texto;
- **S7** a recuperação de senha para de mandar depois do limite, com a
  mesma tela;
- **C7** `x@localhost` e IP literal são recusados no cadastro;
- **C8** o CPF vai mascarado na cópia para a operação;
- **W7** ficha arquivada não entra na lista, não é oferecida no modal nem
  puxada;
- **W9** migrado do iClin fecha na data da anotação, e a exportação em
  Markdown sai na hora de Brasília;
- **T7** total de procedimento acima do campo vira recusa, não erro 500;
- **T10** caractere de controle sai do texto da guia, e o que restar vira
  recusa com a guia;
- **C10** o encerramento sem e-mail registra `error`, que é o que a trilha
  conhece;
- **C11** a recusa de e-mail descartável no convite de equipe entra na
  trilha, com quem convidou.

Tudo numa transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_revisao_grupo1.py
"""
import io
import smtplib
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest import mock

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False
dj_settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from django.utils import timezone
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from pypdf import PdfReader

from accounts.models import User
from audit.models import AuditEvent
from base.validators import _dv_cnpj, is_valid_cnpj, normalizar_cnpj
from catalogs.descartaveis import e_descartavel
from clinical.models import Encounter, EncounterKind, EncounterStatus
from communications import email as email_mod
from documents import issuance
from documents.models import MedicalDocumentKind
from documents.pdf import render_medical_document_pdf
from documents.pdf.prescription import SIMPLE
from patients.models import Patient, PatientStatus, RegistrationStage
from reporting.acervo import atendimentos_markdown
from scheduling import espera
from scheduling.espera import EsperaError
from tenancy import contract
from tenancy.context import AccessContext
from tenancy.contracts import _documento_para_operacao
from tenancy.invitations import issue_invitation
from tenancy.models import ClinicProfile, InvitationPurpose, Membership, Role, Tenant, TenantStatus
from tenancy.plans import PlanCode
from tenancy.services import accept_platform_invitation
from tiss import guias
from tiss.xml import XmlInvalido, _Escritor, latin1

mail.outbox = []
falhas = []
SENHA = 'S3nhaF0rteDeVerdade!2026'


def conferir(nome, ok, detalhe=''):
    print(f'  [{"ok" if ok else "FALHA"}] {nome}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(nome)


def cnpj_alfa(corpo):
    d1 = _dv_cnpj(corpo, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return corpo + d1 + _dv_cnpj(corpo + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])


def pdf_texto(dados):
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(dados)).pages)


def contexto(vinculo):
    return AccessContext(
        user_id=vinculo.user_id, tenant_id=vinculo.tenant_id, membership_id=vinculo.id,
        permissions=frozenset(vinculo.roles or []), request_id=None,
        tenant_status=vinculo.tenant.status, capabilities=frozenset(),
    )


def console(su):
    s = Client()
    s.force_login(su)
    requisicao = type('R', (), {'session': s.session, 'user': su})()
    otp_login(requisicao, TOTPDevice.objects.filter(user=su, confirmed=True).first())
    # As ações graves do console pedem o código recente (revisão de 2026-11-02, S6).
    from accounts.mfa import mark_recent_mfa
    mark_recent_mfa(requisicao)
    requisicao.session.save()
    s.cookies['sessionid'] = requisicao.session.session_key
    return s


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.get(tenant=tenant, user__email='doctor-a@demo.neurodoc.local')
dono = Membership.objects.filter(tenant=tenant, roles__contains=[Role.OWNER]).first()

try:
    with transaction.atomic():
        print('=== C4. CNPJ alfanumérico ===')
        alfa = cnpj_alfa('12ABC34501DE')
        conferir('o CNPJ alfanumérico é válido', is_valid_cnpj(alfa))
        conferir('com máscara e minúsculas também', is_valid_cnpj(f'{alfa[:2]}.{alfa[2:5]}.{alfa[5:8]}/{alfa[8:12]}-{alfa[12:]}'.lower()))
        conferir('o numérico continua válido', is_valid_cnpj('11.222.333/0001-81'))
        conferir('letra no dígito verificador é recusada', not is_valid_cnpj(alfa[:12] + 'AB'))
        conferir('dígito errado é recusado', not is_valid_cnpj(alfa[:13] + str((int(alfa[13]) + 1) % 10)))
        _, tk = issue_invitation(purpose=InvitationPurpose.PLATFORM, plan=PlanCode.FREE)
        org = accept_platform_invitation(
            tk, 'alfa-roteiro@example.invalid', SENHA, 'CLINICA ALFA LTDA',
            f'{alfa[:2]}.{alfa[2:5]}.{alfa[5:8]}/{alfa[8:12]}-{alfa[12:]}'.lower(),
        )
        org_tenant = org[1]
        org_tenant.refresh_from_db()
        conferir('a clínica guarda o CNPJ com as letras', org_tenant.cnpj == normalizar_cnpj(alfa), org_tenant.cnpj)
        conferir('e não virou pessoa física', not org_tenant.pessoa_fisica and org_tenant.cpf == '')
        conferir('formatado com pontos e barra', org_tenant.documento_formatado == f'{alfa[:2]}.{alfa[2:5]}.{alfa[5:8]}/{alfa[8:12]}-{alfa[12:]}')

        from base.forms import OrganizationSignupForm
        f = OrganizationSignupForm(data={'documento': alfa})
        f.is_valid()
        conferir('o formulário recusa o mesmo CNPJ alfanumérico de novo',
                 'documento' in f.errors and 'não pode ser usado' in str(f.errors['documento']))
        f = OrganizationSignupForm(data={'documento': '529.982.247-25'})
        f.is_valid()
        conferir('onze dígitos continuam sendo CPF', 'documento' not in f.errors, f.errors.get('documento'))

        print('=== C12. Declaração com o CNPJ pontuado ===')
        html = open('templates/scheduling/declaracao.html', encoding='utf-8').read()
        conferir('a declaração usa o documento formatado', 'CNPJ {{ tenant.documento_formatado }}' in html)

        print('=== S3. Teste do servidor de e-mail ===')
        for host in ('127.0.0.1', 'localhost', '10.0.0.5', '169.254.169.254', 'db', 'redis'):
            try:
                email_mod._exigir_host_publico(host, 587)
                conferir(f'{host} é recusado', False)
            except email_mod.EmailSendFailed as exc:
                conferir(f'{host} é recusado sem dizer o que há lá', '127.0.0.1' not in str(exc) and 'refused' not in str(exc).lower())
        sender = email_mod._Sender(header='X <x@example.com>', reply_to='', host='127.0.0.1', port=6379,
                                   user='', password_getter=lambda: '', use_tls=False, use_ssl=False)
        try:
            email_mod.verify_connection(sender)
            conferir('o botão testar recusa o Redis', False)
        except email_mod.EmailSendFailed as exc:
            conferir('o botão testar recusa o Redis com texto para a tela',
                     'internet' in str(exc) and 'Errno' not in str(exc) and '6379' not in str(exc), str(exc))
        auth = email_mod.EmailSendFailed('x')
        auth.__cause__ = smtplib.SMTPAuthenticationError(535, b'5.7.8 user@x.com badcredentials host 10.1.2.3')
        msg = email_mod._mensagem_para_a_tela(auth)
        conferir('falha de senha vira frase, sem a resposta crua', msg == 'O servidor recusou o usuário ou a senha.', msg)
        rede = email_mod.EmailSendFailed('x')
        rede.__cause__ = ConnectionRefusedError(111, 'Connection refused')
        conferir('falha de rede vira frase', email_mod._mensagem_para_a_tela(rede).startswith('Não foi possível conectar'))

        print('=== S4. Marcação no timbre e na assinatura ===')
        perfil = medico.user.physician_profile
        perfil.professional_name = 'DR. ROTEIRO <b'
        perfil.save(update_fields=['professional_name'])
        clinica, _ = ClinicProfile.objects.get_or_create(tenant=tenant)
        clinica.address_line = 'Rua <img src="http://169.254.169.254/x"/> 1'
        clinica.save(update_fields=['address_line'])
        pac = Patient.objects.create(tenant=tenant, full_name='PACIENTE ROTEIRO GRUPO UM',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        enc = Encounter.objects.create(
            tenant=tenant, patient=pac, physician_membership=medico, occurred_at=timezone.now(),
            status=EncounterStatus.IN_PROGRESS, kind=EncounterKind.FREE_TEXT, free_text='Consulta do roteiro.',
        )
        doc = issuance.create_draft(
            tenant, pac, enc, medico, medico.user_id, MedicalDocumentKind.PRESCRIPTION,
            {'prescription_text': 'Dipirona 500mg', 'special_instructions': '', 'prescription_format': SIMPLE},
        )
        try:
            texto = pdf_texto(render_medical_document_pdf(doc))
            conferir('o PDF sai com o nome do médico como texto', 'DR. ROTEIRO <b' in texto)
            conferir('e o endereço com a marcação literal', '<img' in texto)
        except Exception as exc:                                    # noqa: BLE001
            conferir('o PDF sai com nome e endereço com marcação', False, repr(exc))

        print('=== S7. Recuperação de senha com limite ===')
        cache.clear()
        alvo = User.objects.create_user(email='senha-roteiro@example.invalid', password=SENHA,
                                        email_verified_at=timezone.now())
        mail.outbox = []
        respostas = []
        for _ in range(6):
            r = Client(REMOTE_ADDR='203.0.113.9').post('/accounts/password-reset/', {'email': alvo.email})
            respostas.append(r.status_code)
        enviados = [m for m in mail.outbox if alvo.email in m.to]
        conferir('só 3 e-mails saem para o mesmo endereço', len(enviados) == 3, len(enviados))
        conferir('e a tela é a mesma nas seis vezes', set(respostas) == {302}, respostas)
        cache.clear()

        print('=== C7. localhost e IP literal ===')
        conferir('x@localhost é recusado', e_descartavel('x@localhost'))
        conferir('x@[127.0.0.1] é recusado', e_descartavel('x@[127.0.0.1]'))
        conferir('gmail continua passando', not e_descartavel('fulano@gmail.com'))

        print('=== C8. CPF mascarado para a operação ===')
        pf = Tenant(legal_name='DRA PF', cnpj='', cpf='52998224725', slug='pf-roteiro-grupo1', plan=PlanCode.FREE)
        conferir('o CPF vai mascarado', _documento_para_operacao(pf) == '***.982.247-**', _documento_para_operacao(pf))
        conferir('o CNPJ vai inteiro', _documento_para_operacao(tenant) == tenant.documento_formatado)

        print('=== W7. Ficha arquivada na lista de espera ===')
        ctx = contexto(medico)
        arq = Patient.objects.create(tenant=tenant, full_name='PACIENTE ROTEIRO ARQUIVADO',
                                     registration_stage=RegistrationStage.COMPLETE,
                                     birth_date_unknown_reason='Roteiro de verificação.')
        entrada = espera.incluir(ctx, arq)
        Patient.objects.filter(id=arq.id).update(status=PatientStatus.ARCHIVED)
        conferir('o modal não oferece a ficha arquivada',
                 entrada.id not in [e.id for e in espera.opcoes_do_modal(tenant.id, medico.id)])
        try:
            espera.para_puxar(ctx, entrada.id, medico)
            conferir('puxar a ficha arquivada é recusado', False)
        except EsperaError:
            conferir('puxar a ficha arquivada é recusado', True)
        conferir('a espera continua aguardando, para alguém decidir',
                 any(e.id == entrada.id for e in espera.lista(tenant.id)))
        espera.retirar(ctx, entrada, motivo='roteiro')
        arq.refresh_from_db()
        try:
            espera.incluir(ctx, arq)
            conferir('incluir ficha arquivada é recusado', False)
        except EsperaError:
            conferir('incluir ficha arquivada é recusado', True)

        print('=== W9. Migrado do iClin e a exportação ===')
        from django.db.models import F
        conferir('nenhum migrado do iClin fecha fora da data da anotação',
                 not Encounter.objects.filter(legacy_id__startswith='iclin:').exclude(finalized_at=F('occurred_at')).exists())
        fonte = open('clinical/management/commands/import_atendimentos_xml.py', encoding='utf-8').read()
        conferir('a migração nova grava a data da anotação', 'finalized_at=quando' in fonte)
        noite = timezone.make_aware(datetime(2026, 10, 20, 22, 30), timezone.get_current_timezone())
        md = atendimentos_markdown([{
            'paciente_id': 1, 'paciente': 'X', 'numero_do_prontuario': '', 'data': noite.astimezone(dt_timezone.utc),
            'medico': 'Dr', 'tipo': 'Texto livre', 'situacao': 'Finalizado',
        }])
        conferir('a exportação mostra 22:30 do dia 20, e não 01:30 do dia 21', '20/10/2026 22:30' in md, md[-120:])

        print('=== T7. Total acima do campo ===')
        conferir('o teto do item é o do campo', guias.TETO_VALOR_ITEM == Decimal('99999999.99'))
        conferir('999 × R$ 99.999.999,99 passa do teto',
                 guias.total_do_item(999, Decimal('99999999.99'), Decimal('1.00')) > guias.TETO_VALOR_ITEM)
        fonte = open('tiss/guias.py', encoding='utf-8').read()
        conferir('gravar_item recusa acima do teto e traduz o full_clean',
                 '> TETO_VALOR_ITEM' in fonte and 'raise GuiaRecusada(\' \'.join(exc.messages))' in fonte)

        print('=== T10. Caractere de controle ===')
        conferir('controle sai do texto', latin1('A\x01B\x7fC\x9fD') == 'ABCD', repr(latin1('A\x01B\x7fC\x9fD')))
        conferir('acento continua', latin1('JOÃO') == 'JOÃO')
        from lxml import etree
        w = _Escritor('4.03.00', numero_guia='G-1')
        try:
            w.el(etree.Element('raiz'), 'campo', 'a\x00b')
            conferir('o que escapar vira recusa com a guia', False)
        except XmlInvalido as exc:
            conferir('o que escapar vira recusa com a guia', 'G-1' in str(exc) and 'campo' in str(exc))

        print('=== C10. Encerramento sem e-mail na trilha ===')
        su = User.objects.create_superuser(email='su-roteiro-grupo1@example.invalid', password=None,
                                           email_verified_at=timezone.now())
        TOTPDevice.objects.create(user=su, name='roteiro-grupo1', confirmed=True)
        alvo_t = Tenant.objects.create(legal_name='CLINICA ROTEIRO ENCERRA', cnpj='11222333000181',
                                       slug='roteiro-grupo1-encerra', plan=PlanCode.FREE)
        s = console(su)
        with mock.patch('tenancy.encerramento.avisar_encerramento', return_value=0):
            s.post(f'/instalacao/organizacoes/{alvo_t.id}/estado/', {'status': 'closed', 'status_note': 'roteiro'})
        ev = AuditEvent.objects.filter(action='tenancy.encerramento_avisado', tenant_id=alvo_t.id).first()
        conferir('a falha de aviso vai como error', ev is not None and ev.outcome == 'error', ev and ev.outcome)
        s.post(f'/instalacao/organizacoes/{alvo_t.id}/estado/', {'status': 'closed', 'status_note': 'roteiro 2'})
        conferir('encerrar de novo não registra outro encerramento',
                 AuditEvent.objects.filter(action='tenancy.tenant_status_changed', tenant_id=alvo_t.id).count() == 1)
        fonte = open('ops/superadmin.py', encoding='utf-8').read()
        conferir('a troca relê a organização travada', 'select_for_update().get(id=tenant.id)' in fonte)

        print('=== C11. Convite de equipe com e-mail descartável ===')
        from catalogs.models import DominioDescartavel
        DominioDescartavel.objects.get_or_create(dominio='descartavel-roteiro.example')
        c = Client()
        c.force_login(dono.user)
        sessao = c.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()
        antes = AuditEvent.objects.filter(action='accounts.email_descartavel_recusado').count()
        c.post('/app/org/equipe/',
               {'email': 'novo@descartavel-roteiro.example', 'roles': ['secretary']})
        ev = AuditEvent.objects.filter(action='accounts.email_descartavel_recusado').order_by('-created_at').first()
        conferir('a recusa no convite entra na trilha',
                 AuditEvent.objects.filter(action='accounts.email_descartavel_recusado').count() == antes + 1)
        conferir('com quem convidou e a clínica', ev is not None and ev.actor_id == dono.user_id and ev.tenant_id == tenant.id)
        conferir('e com o domínio, sem o endereço',
                 ev is not None and ev.integrity_metadata.get('dominio') == 'descartavel-roteiro.example'
                 and 'novo@' not in str(ev.integrity_metadata))
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('Primeiro grupo da revisão: tudo confere.')
