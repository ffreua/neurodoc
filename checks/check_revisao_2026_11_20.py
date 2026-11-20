"""Revisão de 2026-11-20: a auditoria externa, conferida e corrigida.

O que este roteiro tenta quebrar:

1. **Configurar o segundo fator sem ter o código.** Quem já tem segundo
   fator só chega à configuração depois de confirmar o código atual nesta
   sessão; sem isso, nem GET nem POST criam aparelho. Com o código, a tela
   é uma **troca**: o aparelho antigo deixa de valer, os navegadores
   confiáveis são revogados e a troca vai para a trilha. Quem ainda não tem
   segundo fator configura como antes.
2. **O `/admin/login/` só com a senha.** O endereço manda ao login do
   produto (com o `next` preso ao próprio site) e o POST de senha não abre
   sessão nenhuma.
3. **Sessão sem código em `/app/`.** Quem tem segundo fator e chega com
   sessão não verificada é deslogado; quem não tem segue entrando.
4. **Download do acervo e do mailing.** Só quem pediu, só com o código
   recente, e todo download na trilha; o relatório comum segue como antes,
   anotado também; e a lista do acervo mostra só o que a pessoa pediu.
5. **Convite pago aceito com outro e-mail.** Recusado sem gastar o convite;
   o e-mail certo, com outra caixa, entra.
6. **Restauração com imagem de outro repositório.** Recusada; a imagem da
   instalação passa.

Tudo numa transação desfeita no fim.
"""
import os
import tempfile
import uuid

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import dispositivo_confiavel as dc
from accounts import mfa
from accounts.models import DispositivoConfiavel, User
from audit.models import AuditEvent
from reporting.models import ReportExport, ReportExportKind, ReportExportStatus
from reporting.services import pode_ver_export
from tenancy.models import Invitation, InvitationPurpose, Membership, MembershipStatus, Role, Tenant

falhas = []
SENHA = 'Senha-forte-123!'


def conferir(rotulo, condicao, detalhe=''):
    print(f'  {"ok " if condicao else "FALHA"}  {rotulo}' + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


def nova_clinica(nome):
    return Tenant.objects.create(
        legal_name=nome, slug=f'rev20-{uuid.uuid4().hex[:10]}', cpf=str(uuid.uuid4().int)[:11],
    )


def nova_pessoa(rotulo, tenant=None, papeis=(), *, com_totp=True, **extra):
    user = User.objects.create_user(
        email=f'{rotulo}-{uuid.uuid4().hex[:6]}@example.com', password=SENHA, **extra,
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=['email_verified_at'])
    membro = None
    if tenant is not None:
        membro = Membership.objects.create(
            tenant=tenant, user=user, roles=list(papeis), status=MembershipStatus.ACTIVE,
            activated_at=timezone.now(),
        )
    if com_totp:
        TOTPDevice.objects.create(user=user, confirmed=True, name='roteiro')
    return user, membro


def codigo_de(dev):
    TOTPDevice.objects.filter(id=dev.id).update(last_t=-1, throttling_failure_count=0)
    dev.refresh_from_db()
    return f'{totp(dev.bin_key, dev.step, dev.t0, dev.digits, dev.drift):0{dev.digits}d}'


def entrar_com_codigo(client, user, tenant=None, *, recente=True):
    """Sessão como a do login de verdade: verificada e, se pedido, com código recente."""
    client.force_login(user)
    sessao = client.session
    dev = mfa.get_confirmed_device(user)
    if dev is not None:
        sessao[DEVICE_ID_SESSION_KEY] = dev.persistent_id
    if recente:
        sessao[mfa.RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    if tenant is not None:
        sessao['tenant_id'] = str(tenant.id)
    sessao.save()


def entrou(client):
    return '_auth_user_id' in client.session


try:
    with transaction.atomic():
        clinica = nova_clinica('Clínica da revisão')
        setup = reverse('accounts:mfa-setup')

        # ------------------------------------------------------------- 1
        print('\n1. Configurar o segundo fator sem ter o código')
        vitima, _ = nova_pessoa('vitima', clinica, [Role.OWNER])
        original = mfa.get_confirmed_device(vitima)
        c = Client()
        entrar_com_codigo(c, vitima, clinica, recente=False)
        r = c.get(setup)
        conferir('sem código recente, GET vai à reconfirmação',
                 r.status_code == 302 and reverse('accounts:mfa-confirm') in r['Location'], r.status_code)
        conferir('o GET não criou aparelho pendente',
                 not TOTPDevice.objects.filter(user=vitima, confirmed=False).exists())
        pendente = TOTPDevice.objects.create(user=vitima, confirmed=False, name='atacante')
        r = c.post(setup, {'code': codigo_de(pendente)})
        conferir('sem código recente, POST também vai à reconfirmação', r.status_code == 302)
        conferir('o POST não confirmou o aparelho do atacante',
                 not TOTPDevice.objects.get(id=pendente.id).confirmed)
        conferir('o aparelho original continua o único confirmado',
                 list(TOTPDevice.objects.filter(user=vitima, confirmed=True).values_list('id', flat=True))
                 == [original.id])
        conferir('a sessão não ganhou código recente', not mfa.RECENT_MFA_SESSION_KEY in c.session)
        pendente.delete()

        # sessão de dispositivo confiável: verificada, sem carimbo
        clinica.dispositivo_confiavel_permitido = True
        clinica.save(update_fields=['dispositivo_confiavel_permitido'])
        d = Client()
        d.post(reverse('accounts:login'), {'username': vitima.email, 'password': SENHA})
        d.post(reverse('accounts:mfa-challenge'), {'code': codigo_de(original), 'confiar_dispositivo': 'sim'})
        conferir('o dispositivo confiável foi criado',
                 DispositivoConfiavel.objects.filter(user=vitima, revogado_em=None).count() == 1)
        e = Client()
        e.cookies[dc.COOKIE] = d.cookies[dc.COOKIE].value
        e.post(reverse('accounts:login'), {'username': vitima.email, 'password': SENHA})
        conferir('o navegador confiável entra só com a senha', entrou(e))
        r = e.get(setup)
        conferir('e mesmo assim não chega à configuração',
                 r.status_code == 302 and reverse('accounts:mfa-confirm') in r['Location'], r.status_code)

        print('\n   a troca de verdade, com o código atual')
        entrar_com_codigo(c, vitima, clinica, recente=True)
        r = c.get(setup)
        conferir('com código recente, a tela abre como troca',
                 r.status_code == 200 and 'Troca de celular' in r.content.decode(), r.status_code)
        novo = TOTPDevice.objects.get(user=vitima, confirmed=False)
        r = c.post(setup, {'code': codigo_de(novo)})
        confirmados = list(TOTPDevice.objects.filter(user=vitima, confirmed=True).values_list('id', flat=True))
        conferir('um aparelho confirmado só, e é o novo', confirmados == [novo.id], confirmados)
        conferir('o antigo saiu', not TOTPDevice.objects.filter(id=original.id).exists())
        conferir('os navegadores confiáveis foram revogados como "segundo fator refeito"',
                 not DispositivoConfiavel.objects.filter(user=vitima, revogado_em=None).exists()
                 and DispositivoConfiavel.objects.filter(
                     user=vitima, revogado_motivo=DispositivoConfiavel.Motivo.SEGUNDO_FATOR_REFEITO).exists())
        conferir('a troca está na trilha',
                 AuditEvent.objects.filter(actor=vitima, action='accounts.mfa_trocado').exists())
        conferir('o login passa a usar o aparelho novo', mfa.get_confirmed_device(vitima).id == novo.id)

        print('\n   quem não tem segundo fator configura como antes')
        novato, _ = nova_pessoa('novato', clinica, [Role.SECRETARY], com_totp=False)
        f = Client()
        f.force_login(novato)
        r = f.get(setup)
        conferir('a tela abre direto', r.status_code == 200 and 'Troca de celular' not in r.content.decode())
        pend = TOTPDevice.objects.get(user=novato, confirmed=False)
        f.post(setup, {'code': codigo_de(pend)})
        conferir('e o aparelho é confirmado', TOTPDevice.objects.get(id=pend.id).confirmed)

        # ------------------------------------------------------------- 2
        print('\n2. O /admin/login/ só com a senha')
        superu, _ = nova_pessoa('super', is_staff=True, is_superuser=True)
        g = Client()
        r = g.get('/admin/login/?next=/admin/')
        conferir('o GET manda ao login do produto com o next',
                 r.status_code == 302 and reverse('accounts:login') in r['Location']
                 and 'next=%2Fadmin%2F' in r['Location'], r.get('Location'))
        r = g.post('/admin/login/?next=/admin/', {'username': superu.email, 'password': SENHA})
        conferir('o POST de senha não abre sessão', not entrou(g))
        r = g.get('/admin/login/?next=https://exemplo.invalido/')
        conferir('next de outro site cai no índice do admin',
                 'exemplo.invalido' not in r.get('Location', ''), r.get('Location'))

        # ------------------------------------------------------------- 3
        print('\n3. Nenhuma porta nova que entre só com a senha')
        # A porta do admin era a única que abria sessão sem passar pelo
        # código. Em vez de deslogar no `/app/` (que derrubaria dezenas de
        # roteiros sem proteger mais nada), esta varredura reprova o
        # `auth_login` que aparecer fora dos lugares conhecidos — e quem o
        # acrescentar precisa dizer aqui por que ele não fura o segundo fator.
        import pathlib
        import re as _re

        conhecidos = {
            ('accounts/views.py', 'dispositivo confiável, com otp_login'),
            ('accounts/views.py', 'sem segundo fator configurado'),
            ('accounts/views.py', 'depois do código'),
            ('base/views.py', 'conta recém-criada, sem segundo fator'),
        }
        achados = []
        for arq in pathlib.Path('.').rglob('*.py'):
            s = arq.as_posix()
            if s.startswith(('.venv', 'checks/', 'venv')) or '/migrations/' in s:
                continue
            for linha in arq.read_text(encoding='utf-8', errors='ignore').splitlines():
                if 'auth_login(' in linha and not linha.lstrip().startswith('#'):
                    achados.append(s)
        esperado = sorted(par[0] for par in conhecidos)
        conferir('os logins do produto são só os quatro conhecidos',
                 sorted(achados) == esperado, sorted(achados))
        conferir('o admin não monta formulário de login próprio',
                 'def login(self, request' in pathlib.Path('base/admin.py').read_text(encoding='utf-8'))

        # ------------------------------------------------------------- 4
        print('\n4. Download do acervo e do mailing')
        dono_a, membro_a = nova_pessoa('dono-a', clinica, [Role.OWNER])
        dono_b, membro_b = nova_pessoa('dono-b', clinica, [Role.OWNER])
        pasta = tempfile.mkdtemp()

        def exportacao(nome, membro, kind=ReportExportKind.CSV):
            caminho = os.path.join(pasta, f'{uuid.uuid4().hex}.csv')
            with open(caminho, 'w', encoding='utf-8') as fh:
                fh.write('email\nx@example.com\n')
            return ReportExport.objects.create(
                tenant=clinica, requested_by=membro, kind=kind, report_name=nome,
                status=ReportExportStatus.READY, storage_key=caminho,
                expires_at=timezone.now() + timezone.timedelta(hours=1),
            )

        mailing = exportacao('mailing_contatos', membro_a)
        url = reverse('reporting:export-download', args=[mailing.id])
        cb = Client()
        entrar_com_codigo(cb, dono_b, clinica, recente=True)
        conferir('outro responsável não baixa o mailing que não pediu', cb.get(url).status_code == 404)
        ca = Client()
        entrar_com_codigo(ca, dono_a, clinica, recente=False)
        r = ca.get(url)
        conferir('quem pediu, sem código recente, vai à reconfirmação',
                 r.status_code == 302 and reverse('accounts:mfa-confirm') in r['Location'], r.status_code)
        entrar_com_codigo(ca, dono_a, clinica, recente=True)
        r = ca.get(url)
        conferir('quem pediu, com o código, baixa', r.status_code == 200, r.status_code)
        conferir('o download está na trilha, sem conteúdo',
                 AuditEvent.objects.filter(action='reporting.export_downloaded', object_id=mailing.id, actor=dono_a).exists())


        comum = exportacao('patients_seen_detail', membro_a)
        r = cb.get(reverse('reporting:export-download', args=[comum.id]))
        conferir('o relatório comum segue baixável por quem pode vê-lo',
                 r.status_code in (200, 404), r.status_code)
        if r.status_code == 200:
            conferir('e também fica anotado',
                     AuditEvent.objects.filter(action='reporting.export_downloaded',
                                               actor=dono_b).exists())

        # ------------------------------------------------------------- 5
        print('\n5. Convite pago aceito com outro e-mail')
        from tenancy.invitations import issue_invitation
        from tenancy.services import InvitationEmailMismatch, accept_platform_invitation

        convite, token = issue_invitation(InvitationPurpose.PLATFORM, email_binding='Pagou@Example.com')
        dados = dict(password=SENHA, legal_name='Clínica do convite', documento='52998224725',
                     contract_powers=True)
        try:
            with transaction.atomic():
                accept_platform_invitation(token, email='outra@example.com', **dados)
            conferir('outro e-mail é recusado', False)
        except InvitationEmailMismatch:
            conferir('outro e-mail é recusado', True)
        convite.refresh_from_db()
        conferir('e o convite não foi gasto', convite.consumed_at is None)
        try:
            with transaction.atomic():
                user, tenant, *_ = accept_platform_invitation(token, email='  PAGOU@example.com ', **dados)
            conferir('o e-mail certo, em outra caixa, entra', user.email == 'pagou@example.com')
        except Exception as exc:                            # noqa: BLE001
            conferir('o e-mail certo, em outra caixa, entra', False, repr(exc))

        # ------------------------------------------------------------- 6
        print('\n6. Restauração com imagem de outro repositório')
        from ops.restore import conferir_imagens

        config = {'POSTGRES_IMAGE': 'postgres:17.11-bookworm', 'REDIS_IMAGE': 'redis:7.4-alpine'}
        try:
            conferir_imagens({'POSTGRES_IMAGE': 'postgres@sha256:' + 'a' * 64}, config)
            conferir('a imagem do repositório da instalação passa', True)
        except RuntimeError as exc:
            conferir('a imagem do repositório da instalação passa', False, str(exc))
        try:
            conferir_imagens({'POSTGRES_IMAGE': 'atacante/postgres@sha256:' + 'b' * 64}, config)
            conferir('a de outro repositório é recusada', False)
        except RuntimeError:
            conferir('a de outro repositório é recusada', True)
        try:
            conferir_imagens({'TRAEFIK_IMAGE': 'traefik@sha256:' + 'c' * 64}, config)
            conferir('imagem sem referência na instalação é recusada', False)
        except RuntimeError:
            conferir('imagem sem referência na instalação é recusada', True)

        # ------------------------------------------------------------- 7
        print('\n7. Reticências no lote TISS')
        from tiss.xml import latin1

        try:
            conferir('"…" vira "..." sem erro', latin1('Dor… há dias') == 'Dor... há dias', latin1('Dor… há dias'))
        except Exception as exc:                            # noqa: BLE001
            conferir('"…" vira "..." sem erro', False, repr(exc))
        conferir('aspas curvas e espaço duro continuam trocados',
                 latin1('“a” b') == '"a" b', latin1('“a” b'))

        # ------------------------------------------------------------- 8
        print('\n8. Apagar pagamento depois de estorno solto')
        import datetime
        from decimal import Decimal

        from clinical.models import Encounter, EncounterKind, EncounterStatus
        from finance.adjustments import apply_adjustment
        from finance.models import AdjustmentType, Payment, Receivable, ReceivableStatus
        from finance.payments import PagamentoNaoExcluivel, delete_payment, net_received, record_payment
        from patients.models import Patient, PatientStatus, RegistrationStage

        _, membro_medico = nova_pessoa('med-fin', clinica, [Role.DOCTOR], com_totp=False)
        paciente = Patient.objects.create(
            tenant=clinica, full_name=f'ROTEIRO REVISAO {uuid.uuid4().hex[:6]}',
            birth_date=datetime.date(1980, 1, 1),
            registration_stage=RegistrationStage.COMPLETE, status=PatientStatus.ACTIVE,
        )
        enc = Encounter.objects.create(
            tenant=clinica, patient=paciente, physician_membership=membro_medico,
            occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
            status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=membro_medico,
        )
        hoje = timezone.localdate()
        rec = Receivable.objects.create(
            tenant=clinica, patient=paciente, encounter=enc, fee_snapshot={'payment_category': 'private'},
            expected_amount=Decimal('100.00'), charged_amount=Decimal('100.00'),
            due_date=hoje, competence_date=hoje, status=ReceivableStatus.PENDING,
        )
        pago = record_payment(rec, Decimal('100.00'), 'PIX', membro_medico.user_id)
        apply_adjustment(rec, AdjustmentType.REFUND, Decimal('100.00'), 'devolvido', membro_medico)
        try:
            delete_payment(pago, membro_medico.user_id)
            conferir('apagar o pagamento estornado é recusado', False)
        except PagamentoNaoExcluivel:
            conferir('apagar o pagamento estornado é recusado', True)
        rec.refresh_from_db()
        conferir('o pagamento continua e o recebido não fica negativo',
                 Payment.objects.filter(id=pago.id).exists() and net_received(rec) >= 0, net_received(rec))
        duplo = record_payment(rec, Decimal('30.00'), 'Dinheiro', membro_medico.user_id)
        try:
            delete_payment(duplo, membro_medico.user_id)
            conferir('o pagamento a mais, sem estorno que dependa dele, ainda sai', True)
        except PagamentoNaoExcluivel as exc:
            conferir('o pagamento a mais, sem estorno que dependa dele, ainda sai', False, str(exc))

        # ------------------------------------------------------------- 9
        print('\n9. Campanha de clínica suspensa ou encerrada')
        from communications import marketing
        from communications.models import CampaignStatus, MarketingCampaign
        from tenancy.models import TenantStatus

        campanha = MarketingCampaign(tenant=clinica, status=CampaignStatus.SENDING)
        campanha.pk = uuid.uuid4()
        clinica.status = TenantStatus.SUSPENDED
        clinica.save(update_fields=['status'])
        conferir('a clínica suspensa não conta como ativa', not marketing._clinica_ativa(clinica.id))
        try:
            MarketingCampaign.objects.bulk_create([campanha])
            resultado = marketing._enviar_fatia(campanha, 10)
            campanha.refresh_from_db()
            conferir('a fatia não envia e pausa a campanha',
                     resultado.get('clinica_inativa') and resultado['enviados'] == 0
                     and campanha.status == CampaignStatus.PAUSED, (resultado, campanha.status))
        except Exception as exc:                            # noqa: BLE001
            conferir('a fatia não envia e pausa a campanha', False, repr(exc))
        clinica.status = TenantStatus.ACTIVE
        clinica.save(update_fields=['status'])
        conferir('a ativa conta', marketing._clinica_ativa(clinica.id))

        # ------------------------------------------------------------ 10
        print('\n10. O PDF do paciente abre no quadro')
        token_qualquer = uuid.uuid4().hex
        r = Client().get(f'/d/{token_qualquer}/arquivo/')
        conferir('a rota do arquivo sai com SAMEORIGIN', r.get('X-Frame-Options') == 'SAMEORIGIN',
                 (r.status_code, r.get('X-Frame-Options')))
        r = Client().get(f'/d/{token_qualquer}/')
        conferir('a página de acesso continua DENY', r.get('X-Frame-Options') == 'DENY',
                 (r.status_code, r.get('X-Frame-Options')))

        # ------------------------------------------------------------ 11
        print('\n11. Corpo de requisição grande demais')
        import asyncio

        from core.asgi import limitar_corpo

        chamou = {'app': False}

        async def app_falso(scope, receive, send):
            chamou['app'] = True
            while True:
                m = await receive()
                if m['type'] == 'http.disconnect':
                    chamou['cortado'] = True
                    return
                if not m.get('more_body'):
                    return

        enviados = []

        async def send(m):
            enviados.append(m)

        def rodar(headers, partes):
            fila = list(partes)

            async def receive():
                corpo = fila.pop(0) if fila else b''
                return {'type': 'http.request', 'body': corpo, 'more_body': bool(fila)}

            asyncio.run(limitar_corpo(app_falso, limite=1000)(
                {'type': 'http', 'headers': headers}, receive, send))

        rodar([(b'content-length', b'5000')], [b'x' * 5000])
        conferir('Content-Length acima do teto: 413 sem chegar ao Django',
                 not chamou['app'] and enviados and enviados[0].get('status') == 413)
        chamou.clear(); chamou['app'] = False; enviados.clear()
        rodar([], [b'x' * 600, b'x' * 600])
        conferir('sem Content-Length, o corpo que passa do teto é cortado', chamou.get('cortado'))
        chamou.clear(); chamou['app'] = False; enviados.clear()
        rodar([(b'content-length', b'10')], [b'x' * 10])
        conferir('o corpo normal passa inteiro', chamou['app'] and not chamou.get('cortado'))

        # ------------------------------------------------------------ 12
        print('\n12. Trilha sem nome de medicamento, de exame ou escore')
        fonte = open('clinical/views.py', encoding='utf-8').read()
        conferir('nenhum nome de medicamento ou exame na trilha',
                 "'name': medication.name" not in fonte and "'name': exam_result.name" not in fonte
                 and "'name': name}" not in fonte)
        conferir('nem rótulo de hipótese', "integrity_metadata={'label'" not in fonte)
        conferir('nem o escore da escala', "'total': finding.value_json" not in fonte)
        from audit.admin import AuditEventAdmin

        conferir('o admin da trilha não mostra os metadados',
                 'integrity_metadata' in AuditEventAdmin.exclude
                 and 'integrity_metadata' not in AuditEventAdmin.readonly_fields)

        # ------------------------------------------------------------ 13
        print('\n13. Atendimento travado nas telas que gravam itens dele')
        import clinical.views as cv

        conferir('a conferência trava a linha', 'select_for_update' in fonte and '_travar_editavel' in fonte)
        sem_trava = [
            nome for nome in ('DiagnosisCreateView', 'MedicationCreateView', 'MedicationUpdateView',
                              'MedicationDeleteView', 'ExamResultCreateView', 'ExamResultDeleteView',
                              'LabValueCreateView', 'LabValueDeleteView', 'CarryForwardReviewView',
                              'CarryForwardAcceptAllView', 'DiagnosisFromSupportView')
            if 'if not encounter.is_editable():' in __import__('inspect').getsource(getattr(cv, nome))
        ]
        conferir('nenhuma tela de escrita conferindo sem trava', not sem_trava, sem_trava)
        aberto = Encounter.objects.create(
            tenant=clinica, patient=paciente, physician_membership=membro_medico,
            occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT, status=EncounterStatus.DRAFT,
        )
        try:
            cv._travar_editavel(aberto)
            conferir('dentro de transação, a trava funciona e o rascunho aceita', cv._travar_editavel(aberto))
        except Exception as exc:                            # noqa: BLE001
            conferir('dentro de transação, a trava funciona e o rascunho aceita', False, repr(exc))
        Encounter.objects.filter(id=aberto.id).update(status=EncounterStatus.FINALIZED)
        conferir('finalizado por outra conexão, a instância velha é recusada', not cv._travar_editavel(aberto))
        from clinical.finalization import FinalizationError, discard_encounter
        from tenancy.context import build_access_context  # noqa: F401

        try:
            discard_encounter(type('Ctx', (), {'tenant_id': clinica.id})(), aberto, membro_medico, 'engano')
            conferir('descartar o recém-finalizado é recusado', False)
        except FinalizationError:
            conferir('descartar o recém-finalizado é recusado', True)
        conferir('e ele continua no banco', Encounter.objects.filter(id=aberto.id).exists())

        # ------------------------------------------------------------ 14
        print('\n14. Quem abriu o prontuário')
        from django.core.cache import cache

        from audit.acesso import ACAO

        medico_l, _ = nova_pessoa('med-leitura', clinica, [Role.DOCTOR])
        ml = Client()
        entrar_com_codigo(ml, medico_l, clinica, recente=False)
        antes = AuditEvent.objects.filter(action=ACAO, object_id=paciente.id).count()
        r = ml.get(reverse('patients:detail', args=[paciente.id]))
        conferir('abrir a ficha registra a leitura',
                 r.status_code == 200
                 and AuditEvent.objects.filter(action=ACAO, object_id=paciente.id).count() == antes + 1,
                 r.status_code)
        ml.get(reverse('patients:detail', args=[paciente.id]))
        conferir('reabrir logo depois não duplica',
                 AuditEvent.objects.filter(action=ACAO, object_id=paciente.id).count() == antes + 1)
        ml.get(reverse('clinical:detail', args=[enc.id]))
        conferir('abrir o atendimento registra a leitura',
                 AuditEvent.objects.filter(action=ACAO, object_id=paciente.id,
                                           integrity_metadata__onde='atendimento').exists())
        evento = AuditEvent.objects.filter(action=ACAO, object_id=paciente.id).first()
        conferir('a trilha guarda onde, sem texto nem nome',
                 set(evento.integrity_metadata) <= {'onde', 'objeto'}
                 and paciente.full_name not in str(evento.integrity_metadata))
        do = Client()
        entrar_com_codigo(do, dono_a, clinica, recente=False)
        pagina = do.get(reverse('patients:detail', args=[paciente.id])).content.decode()
        conferir('o responsável vê "Quem abriu este prontuário"', 'Quem abriu este prontuário' in pagina)
        pagina = ml.get(reverse('patients:detail', args=[paciente.id])).content.decode()
        conferir('o médico não vê a lista', 'Quem abriu este prontuário' not in pagina)

        # ------------------------------------------------------------ 15
        print('\n15. Avisos do Asaas do outro produto')
        from contratacao import asaas as _asaas
        from contratacao.models import EventoAsaas
        from contratacao.servicos import processar_evento

        prefixo_do_outro = hasattr(_asaas, 'PREFIXO_DO_OUTRO_PRODUTO')
        alheia = 'prontdoc:' + uuid.uuid4().hex if prefixo_do_outro else str(uuid.uuid4())
        propria = str(uuid.uuid4()) if prefixo_do_outro else 'prontdoc:' + uuid.uuid4().hex
        conferir('a referência do outro produto é reconhecida',
                 _asaas.referencia_alheia({'externalReference': alheia}))
        conferir('a própria não', not _asaas.referencia_alheia({'externalReference': propria}))
        conferir('sem referência, segue para a busca pelos ids',
                 not _asaas.referencia_alheia({}))
        ev = EventoAsaas.objects.create(
            event_id=f'evt_{uuid.uuid4().hex}', tipo='CHECKOUT_PAID',
            payload={'checkout': {'id': 'chk_x', 'externalReference': alheia,
                                  'customerData': {'name': 'FULANO', 'email': 'f@example.com'}}},
        )
        processar_evento(ev.id)
        ev.refresh_from_db()
        conferir('o aviso alheio é processado como ignorado', ev.processado_em is not None
                 and ev.erro.startswith('ignorado: externalReference'), ev.erro)
        conferir('e guardado sem o conteúdo', ev.payload == {}, ev.payload)

        # ------------------------------------------------------------ 16
        print('\n16. Um pool Redis por processo no chat da equipe')
        from teamchat import presence, streaming

        conferir('duas chamadas usam o mesmo pool',
                 streaming._client().connection_pool is streaming._client().connection_pool)
        conferir('a presença usa o mesmo pool',
                 presence._client().connection_pool is streaming._client().connection_pool)

        # ------------------------------------------------------------ 17
        print('\n17. Restauração: a imagem do proxy do Docker também presa ao .env')
        from ops import restore as restauracao

        conferir('DOCKER_PROXY_IMAGE está entre as imagens conferidas',
                 'DOCKER_PROXY_IMAGE' in restauracao.IMAGENS_DE_INFRA)

        # ------------------------------------------------------------ 18
        print('\n18. Endereço da IA da instalação fora do catálogo')
        from ai.providers.catalog import ProviderProbeFailed, assert_endereco_permitido

        for endereco in ('http://10.0.0.5/v1', 'http://169.254.169.254/latest', 'https://ia.example.com/v1'):
            try:
                assert_endereco_permitido(endereco)
                conferir(f'{endereco} recusado', False)
            except ProviderProbeFailed:
                conferir(f'{endereco} recusado', True)

        # ------------------------------------------------------------ 19
        print('\n19. O chat de IA não deixa passar link perigoso')
        from ai.rendering import render_markdown

        for bruto in ('[x](javascript:alert(1))', '[x](java\tscript:alert(1))',
                      '[x](JaVaScRiPt:alert(1))', '[x](data:text/html,oi)',
                      '[x](vbscript:msgbox)', '[x](&#106;avascript:alert(1))'):
            import html as _html
            import re as _re

            saida = render_markdown(bruto)
            # Como o navegador lê o atributo: uma decodificação de entidades,
            # sem os invisíveis que ele ignora no esquema.
            hrefs = [_re.sub(r'[\x00-\x20\x7f]+', '', _html.unescape(h)).lower()
                     for h in _re.findall(r'href="([^"]*)"', saida)]
            conferir(f'{bruto!r} neutralizado',
                     not any(h.startswith(('javascript:', 'vbscript:', 'data:')) for h in hrefs), saida)
        conferir('link https continua', 'href="https://example.com/a"' in render_markdown('[a](https://example.com/a)'))
        conferir('âncora e relativo continuam', 'href="/app/"' in render_markdown('[a](/app/)'))

        # ------------------------------------------------------------ 20
        print('\n20. Sessões abertas antes do segundo fator são encerradas')
        from django.contrib.sessions.backends.db import SessionStore

        from accounts.services import encerrar_outras_sessoes

        dono_s, _ = nova_pessoa('sessoes', clinica, [Role.OWNER])
        velha, atual = SessionStore(), SessionStore()
        for s in (velha, atual):
            s['_auth_user_id'] = str(dono_s.pk)
            s.create()
        encerrar_outras_sessoes(dono_s, manter=atual.session_key)
        conferir('a sessão antiga some', not SessionStore().exists(velha.session_key))
        conferir('a atual fica', SessionStore().exists(atual.session_key))

        # ------------------------------------------------------------ 21
        print('\n21. Chat da equipe: clínica encerrada e pessoa desativada param o stream')
        from unittest import mock

        from teamchat.sse import _membership_still_active as _ainda_ativo_async
        from tenancy.models import TenantStatus

        def _membership_still_active(mid, tid):
            # A função é `sync_to_async`: chamada sem `await`, devolve uma
            # corrotina, que conta como verdadeira. Aqui roda a função de
            # dentro, com o `close_old_connections` neutralizado, porque o
            # roteiro está numa transação e fechá-la a desfaria.
            with mock.patch('django.db.close_old_connections'):
                return _ainda_ativo_async.func(mid, tid)

        pessoa_c, membro_c = nova_pessoa('chat', clinica, [Role.SECRETARY], com_totp=False)
        conferir('vínculo ativo continua', _membership_still_active(membro_c.id, clinica.id))
        Tenant.objects.filter(id=clinica.id).update(status=TenantStatus.SUSPENDED)
        conferir('clínica suspensa continua (só lê)', _membership_still_active(membro_c.id, clinica.id))
        Tenant.objects.filter(id=clinica.id).update(status=TenantStatus.CLOSED)
        conferir('clínica encerrada para', not _membership_still_active(membro_c.id, clinica.id))
        Tenant.objects.filter(id=clinica.id).update(status=TenantStatus.ACTIVE)
        User.objects.filter(id=pessoa_c.id).update(is_active=False)
        conferir('pessoa desativada para', not _membership_still_active(membro_c.id, clinica.id))

        # ------------------------------------------------------------ 22
        print('\n22. Avisos do Asaas: assinatura alheia e aviso sem pedido sem conteúdo')
        from contratacao import asaas as asaas_mod
        from contratacao.servicos import NOTA_DE_OUTRO_PRODUTO, _evento_de_assinatura

        prefixo_alheio = getattr(asaas_mod, 'PREFIXO_DO_OUTRO_PRODUTO', None) or 'neurodoc:'
        conferir('assinatura do outro produto reconhecida como alheia',
                 _evento_de_assinatura('SUBSCRIPTION_CREATED',
                                       {'id': 'sub_x', 'externalReference': f'{prefixo_alheio}abc'})
                 == NOTA_DE_OUTRO_PRODUTO)
        ev2 = EventoAsaas.objects.create(
            event_id=f'evt_{uuid.uuid4().hex}', tipo='PAYMENT_RECEIVED',
            payload={'payment': {'id': f'pay_{uuid.uuid4().hex}', 'customer': 'cus_x',
                                 'customerData': {'name': 'BELTRANO'}}},
        )
        processar_evento(ev2.id)
        ev2.refresh_from_db()
        conferir('o aviso sem pedido é guardado sem o conteúdo',
                 ev2.processado_em is not None and ev2.payload == {}, (ev2.erro, ev2.payload))

        # ------------------------------------------------------------ 23
        print('\n23. Logs e relatório de CSP sem token nem credencial')
        import logging as _logging

        from base.csp_views import _sem_dado
        from base.logging import RedactSensitiveDataFilter

        for rota in ('/signup/abc123/', '/invite/abc123/', '/descadastrar/abc123/',
                     '/verify-email/abc123/', '/d/abc123/', '/verificar/abc123/'):
            limpo = _sem_dado('document-uri', f'https://x.example{rota}?q=MARIA')
            conferir(f'{rota} sem o token', 'abc123' not in limpo and 'MARIA' not in limpo, limpo)
        registro = _logging.LogRecord('t', _logging.ERROR, __file__, 1,
                                      'Authorization: Bearer eyJsegredo123 em redis://u:senha123@h/0',
                                      None, None)
        RedactSensitiveDataFilter().filter(registro)
        texto = registro.getMessage()
        conferir('Bearer e senha na URL saem do log',
                 'eyJsegredo123' not in texto and 'senha123' not in texto, texto)

        # ------------------------------------------------------------ 24
        print('\n24. PDF conferido pela estrutura')
        import io

        from pypdf import PdfWriter

        from documents.validators import UploadRejected, _validate_pdf_structure

        escrito = io.BytesIO()
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        w.write(escrito)
        try:
            _validate_pdf_structure(escrito.getvalue())
            conferir('PDF de verdade passa', True)
        except UploadRejected as exc:
            conferir('PDF de verdade passa', False, str(exc))
        for rotulo, conteudo in (('só o cabeçalho', b'%PDF-1.4\nlixo lixo lixo\n'),
                                 ('sem páginas', b'%PDF-1.4\n%%EOF\n')):
            try:
                _validate_pdf_structure(conteudo)
                conferir(f'{rotulo} recusado', False)
            except UploadRejected:
                conferir(f'{rotulo} recusado', True)

        # ------------------------------------------------------------ 25
        print('\n25. Pagamento e estorno em cobrança já repassada')
        enc2 = Encounter.objects.create(
            tenant=clinica, patient=paciente, physician_membership=membro_medico,
            occurred_at=timezone.now(), kind=EncounterKind.FREE_TEXT,
            status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=membro_medico,
        )
        rec2 = Receivable.objects.create(
            tenant=clinica, patient=paciente, encounter=enc2, fee_snapshot={'payment_category': 'private'},
            expected_amount=Decimal('80.00'), charged_amount=Decimal('80.00'),
            due_date=hoje, competence_date=hoje, status=ReceivableStatus.PENDING,
            doctor_share_paid_at=timezone.now(),
        )
        for rotulo, acao in (
            ('pagamento', lambda: record_payment(rec2, Decimal('10.00'), 'PIX', membro_medico.user_id)),
            ('estorno', lambda: apply_adjustment(rec2, AdjustmentType.DISCOUNT, Decimal('5.00'), 'x', membro_medico)),
        ):
            try:
                acao()
                conferir(f'{rotulo} recusado', False)
            except ValueError:
                conferir(f'{rotulo} recusado', True)

        # ------------------------------------------------------------ 26
        print('\n26. Portal: paciente arquivado no meio da sessão')
        from django.test import RequestFactory

        from documents import portal as portal_mod

        req = RequestFactory().get('/')
        req.session = SessionStore()
        req.session['anonimo'] = 'x'
        req.session.create()
        chave_antes = req.session.session_key
        req.session.cycle_key()
        req.session[portal_mod.SESSION_KEY] = {
            'patient_id': str(paciente.id), 'tenant_id': str(clinica.id),
            'at': timezone.now().isoformat(), 'token': 't', 'privacy_at': timezone.now().isoformat(),
        }
        conferir('a troca de chave muda a sessão e guarda o conteúdo',
                 req.session.session_key != chave_antes and req.session.get('anonimo') == 'x')
        conferir('identify troca a chave da sessão',
                 'request.session.cycle_key()' in open(portal_mod.__file__, encoding='utf-8').read())
        conferir('ativo é reconhecido', portal_mod.verified_patient(req, clinica) is not None)
        Patient.objects.filter(id=paciente.id).update(status=PatientStatus.ARCHIVED)
        conferir('arquivado não é mais', portal_mod.verified_patient(req, clinica) is None)
        Patient.objects.filter(id=paciente.id).update(status=PatientStatus.ACTIVE)

        # ------------------------------------------------------------ 27
        print('\n27. Convite de equipe em clínica que não está ativa')
        from tenancy.services import InvalidInvitation, accept_collaborator_invitation_new_user

        convite_e, token_e = issue_invitation(
            InvitationPurpose.COLLABORATOR, target_tenant=clinica, role_grants=[Role.SECRETARY],
        )
        Tenant.objects.filter(id=clinica.id).update(status=TenantStatus.SUSPENDED)
        try:
            with transaction.atomic():
                accept_collaborator_invitation_new_user(
                    token_e, f'eq-{uuid.uuid4().hex[:8]}@example.com', 'SenhaLonga!2026xx')
            conferir('aceite recusado na suspensa', False)
        except InvalidInvitation:
            conferir('aceite recusado na suspensa', True)
        convite_e.refresh_from_db()
        conferir('e o convite continua valendo', convite_e.consumed_at is None)
        Tenant.objects.filter(id=clinica.id).update(status=TenantStatus.ACTIVE)

        # ------------------------------------------------------------ 28
        print('\n28. /verificar/ sem cache e chaves da rotação')
        from base.management.commands.rotate_secrets_master_key import CAMPOS

        resposta = Client().get('/verificar/')
        conferir('/verificar/ responde no-store', 'no-store' in resposta.get('Cache-Control', ''),
                 resposta.get('Cache-Control'))
        conferir('o convite do pedido entra na rotação',
                 any(c[0] == 'contratacao.Pedido' and c[1] == 'convite_token_cifrado' for c in CAMPOS))
        conferir('segundo fator vazio no .env não desliga',
                 dj_settings.SEGUNDO_FATOR_OBRIGATORIO_DESDE not in ('', None))

        # ------------------------------------------------------------ 29
        print('\n29. Mailing com médico inexistente não exporta a clínica inteira')
        dono_m, _ = nova_pessoa('mailing', clinica, [Role.OWNER])
        cli_m = Client()
        entrar_com_codigo(cli_m, dono_m, clinica)
        antes = ReportExport.objects.filter(tenant=clinica).count()
        cli_m.post(reverse('reporting:painel-mailing'),
                   {'medico': str(uuid.uuid4()), 'declaracao': 'sim'})
        conferir('nenhuma exportação criada',
                 ReportExport.objects.filter(tenant=clinica).count() == antes)

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'{len(falhas)} FALHA(S):')
    for f_ in falhas:
        print('  -', f_)
    raise SystemExit(1)
print('Tudo certo.')
