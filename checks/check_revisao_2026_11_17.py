"""Revisão de 2026-11-17: segurança relatada por @meirakalile-ship-it, IA por tarefa,
parcelamento e TISS automático.

O desenvolvedor @meirakalile-ship-it leu o código e apontou seis pontos de
segurança (mais dois que a §25 do PRE_DEPLOY_AUDIT já anotava). Todos
procediam, no NeuroDoc e no ProntDoc. Este roteiro tenta quebrar cada
correção — e as três mudanças da mesma rodada:

1. o admin do Django lista as linhas de conteúdo clínico, mas não abre
   nenhuma (o superusuário via queixa, conduta e resposta da IA sem trilha);
2. revogar o certificado apaga o PFX cifrado e a chave que o abre;
3. a sessão de assinatura dura no máximo 4 h, inclusive as abertas antes;
4. o rodapé do documento não afirma "ICP-Brasil", que o envio não confere;
5. o código de recuperação do 2FA tem limite, e o que não tem a forma dele
   não deriva senha nenhuma;
6. a chave antiga da rotação sai da linha de comando; o molde do `.env`
   nasce com segundo fator exigido e CSP aplicada;
7. a trilha recusa `TRUNCATE`; o motivo escrito pelo médico não vai para ela;
8. o modelo pesado da instalação atende apoio diagnóstico e relatório;
9. o parcelamento no cartão segue a redação do contrato;
10. contratar um plano com TISS o libera, inclusive na conversão da
    degustação, e isso fica na trilha.

Roda dentro de uma transação desfeita no fim: nada fica na base. O arquivo
temporário do certificado é criado e apagado aqui.
"""
import inspect
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings as dj_settings
from django.contrib import admin
from django.core.cache import cache
from django.db import connection, transaction
from django.test import RequestFactory
from django.utils import timezone

from accounts import mfa
from accounts.models import User
from audit.models import AuditEvent
from documents import credentials, signing_sessions
from documents.models import SigningCredential, SigningCredentialStatus, SigningSession
from tenancy.models import Membership, MembershipStatus, Role, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}{(" — " + str(detalhe)) if detalhe else ""}')
    if not ok:
        falhas.append(rotulo + (f' ({detalhe})' if detalhe else ''))


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
).first()
if medico is None:
    raise SystemExit('A clínica de demonstração não tem médico ativo.')

fabrica = RequestFactory()
superusuario = SimpleNamespace(is_active=True, is_staff=True, is_superuser=True,
                               is_authenticated=True, has_perm=lambda *a, **k: True,
                               has_module_perms=lambda *a, **k: True)

try:
    with transaction.atomic():
        print('=== 1. admin: a linha aparece, o registro não abre ===')
        from ai.chat_models import ChatMessage, ChatSession
        from ai.models import AIArtifact, AIJob
        from clinical.models import (
            CarryForwardItem, ClinicalAmendment, Encounter, EncounterDiagnosis, ExaminationFinding,
        )
        from documents.models import AttachmentOcrPage, MedicalDocument
        from patients.models import Observation
        from teamchat.models import Message

        pedido = fabrica.get('/admin/')
        pedido.user = superusuario
        for modelo in (Encounter, ExaminationFinding, EncounterDiagnosis, CarryForwardItem,
                       ClinicalAmendment, AIJob, AIArtifact, ChatSession, ChatMessage,
                       MedicalDocument, AttachmentOcrPage, Observation, Message):
            modelo_admin = admin.site._registry.get(modelo)
            if modelo_admin is None:
                conferir(f'{modelo.__name__}: registrado no admin', False)
                continue
            conferir(f'{modelo.__name__}: a lista continua visível',
                     modelo_admin.has_view_permission(pedido) is True)
            conferir(f'{modelo.__name__}: o registro aberto é recusado',
                     modelo_admin.has_view_permission(pedido, modelo()) is False)
            conferir(f'{modelo.__name__}: nem alterar nem apagar pelo admin',
                     not modelo_admin.has_change_permission(pedido, modelo())
                     and not modelo_admin.has_delete_permission(pedido, modelo()))

        print('=== 2. revogar o certificado descarta o material ===')
        fd, caminho = tempfile.mkstemp(suffix='.pfx.enc')
        os.write(fd, b'cifrado-de-mentira')
        os.close(fd)
        agora = timezone.now()
        credencial = SigningCredential.objects.create(
            tenant=tenant, physician=medico, ciphertext_path=caminho,
            wrapped_key_metadata={'wrapped_key': 'embrulhada-de-mentira'},
            certificate_serial='abc123', certificate_fingerprint='f' * 64, issuer='CN=Teste',
            not_before=agora - timedelta(days=1), not_after=agora + timedelta(days=300),
        )
        sessao = SigningSession.objects.create(
            tenant=tenant, physician=medico, credential=credencial, duration_hours=2,
            expires_at=agora + timedelta(hours=2), mfa_at=agora, session_binding_hash='x' * 64,
            encrypted_unlock_material='senha-cifrada', ephemeral_key_id=uuid.uuid4(),
        )
        credentials.revoke_credential(credencial)
        credencial.refresh_from_db()
        sessao.refresh_from_db()
        conferir('status revogado', credencial.status == SigningCredentialStatus.REVOKED)
        conferir('o arquivo cifrado foi apagado', not Path(caminho).exists())
        conferir('a chave embrulhada foi descartada (só a data fica)',
                 set(credencial.wrapped_key_metadata) == {'descartada_em'}, credencial.wrapped_key_metadata)
        conferir('o caminho do arquivo sumiu', credencial.ciphertext_path == '')
        conferir('série, impressão digital e validade ficam',
                 credencial.certificate_serial == 'abc123' and credencial.not_after is not None)
        conferir('a sessão aberta com ele foi encerrada', sessao.revoked_at is not None)
        conferir('descartar de novo não faz nada', credentials.descartar_material(credencial) is False)
        try:
            credentials.decrypt_pfx_bytes(credencial)
            conferir('o PFX não abre mais', False)
        except Exception:
            conferir('o PFX não abre mais', True)

        print('=== 3. sessão de assinatura: no máximo 4 h ===')
        conferir('durações oferecidas: 2 e 4 h', signing_sessions.ALLOWED_DURATIONS_HOURS == (2, 4))
        credencial2 = SigningCredential.objects.create(
            tenant=tenant, physician=medico, ciphertext_path='/tmp/nao-existe.pfx.enc',
            wrapped_key_metadata={'wrapped_key': 'x'}, certificate_serial='def456',
            certificate_fingerprint='e' * 64, issuer='CN=Teste',
            not_before=agora - timedelta(days=1), not_after=agora + timedelta(days=300),
        )
        sessao_de_12h = SigningSession.objects.create(
            tenant=tenant, physician=medico, credential=credencial2, duration_hours=12,
            expires_at=agora + timedelta(hours=7), mfa_at=agora - timedelta(hours=5),
            session_binding_hash=signing_sessions.hashlib.sha256(b'chave-da-sessao').hexdigest(),
            encrypted_unlock_material='x', ephemeral_key_id=uuid.uuid4(),
        )
        SigningSession.objects.filter(id=sessao_de_12h.id).update(created_at=agora - timedelta(hours=5))
        falso = SimpleNamespace(session=SimpleNamespace(session_key='chave-da-sessao'))
        conferir('sessão de 12 h aberta há 5 h não vale mais',
                 signing_sessions.get_active_session(falso, medico) is None)
        SigningSession.objects.filter(id=sessao_de_12h.id).update(created_at=agora - timedelta(hours=1))
        conferir('e a aberta há 1 h continua valendo',
                 signing_sessions.get_active_session(falso, medico) is not None)

        print('=== 4. rodapé: "certificado digital", não "ICP-Brasil" ===')
        from sncr.pdf_oficial import registro_de_assinatura

        texto = registro_de_assinatura(
            SimpleNamespace(professional_name='Dra. Teste', crm_number='1', crm_state='SP'),
            SimpleNamespace(certificate_serial='abc'), timezone.now(),
        )
        conferir('o registro da receita não afirma ICP-Brasil', 'ICP-Brasil' not in texto, texto)
        conferir('e diz que é certificado digital', 'certificado digital' in texto)
        from documents.pdf import common as pdf_comum

        conferir('o rodapé dos demais documentos também não',
                 "'Assinado digitalmente (PAdES/ICP-Brasil)'" not in inspect.getsource(pdf_comum))

        print('=== 5. código de recuperação com limite ===')
        usuario = User.objects.create_user(
            f'roteiro-rec-{uuid.uuid4().hex[:8]}@example.invalid', 'Senha-descartavel-123!',
        )
        codigos = mfa.generate_recovery_codes(usuario, count=3)
        cache.delete(mfa._chave_recuperacao(usuario))
        with mock.patch('accounts.mfa.check_password', wraps=mfa.check_password) as espiao:
            conferir('TOTP de seis dígitos não é código de recuperação',
                     mfa.consume_recovery_code(usuario, '123456') is False)
            conferir('e não derivou senha nenhuma', espiao.call_count == 0, espiao.call_count)
        for _ in range(mfa.MAX_RECUPERACAO):
            mfa.consume_recovery_code(usuario, '0123456789')
        with mock.patch('accounts.mfa.check_password', wraps=mfa.check_password) as espiao:
            conferir('passado o teto, até o código certo é recusado',
                     mfa.consume_recovery_code(usuario, codigos[0]) is False)
            conferir('sem derivar senha', espiao.call_count == 0, espiao.call_count)
        cache.delete(mfa._chave_recuperacao(usuario))
        conferir('vencida a janela, o código certo vale (com caixa alta e hífen)',
                 mfa.consume_recovery_code(usuario, codigos[0][:5].upper() + '-' + codigos[0][5:]) is True)
        conferir('e vale uma vez só', mfa.consume_recovery_code(usuario, codigos[0]) is False)
        cache.delete(mfa._chave_recuperacao(usuario))

        print('=== 6. rotação de chave e molde do .env ===')
        from base.management.commands.rotate_secrets_master_key import Command as Rotacao

        parser = Rotacao().create_parser('manage.py', 'rotate_secrets_master_key')
        opcoes = parser.parse_args(['--old-key-stdin', '--dry-run'])
        conferir('a chave antiga pode vir da entrada padrão', opcoes.old_key_stdin is True)
        molde = Path(dj_settings.BASE_DIR) / '.env.example'
        if molde.exists():
            from ops.env import read_env

            valores = read_env(molde)
            conferir('molde: segundo fator exigido (vazio = padrão do código)',
                     valores.get('SEGUNDO_FATOR_OBRIGATORIO_DESDE') == '', valores.get('SEGUNDO_FATOR_OBRIGATORIO_DESDE'))
            conferir('molde: CSP aplicada', valores.get('CSP_ENFORCE') == 'True', valores.get('CSP_ENFORCE'))
        else:
            print('  (o .env.example não está na imagem; conferido só o comando)')

        print('=== 7. trilha: sem TRUNCATE e sem o texto do médico ===')
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_auditevent_sem_truncate'"
            )
            conferir('o gatilho de TRUNCATE existe', cursor.fetchone()[0] == 1)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('TRUNCATE audit_auditevent')
            conferir('TRUNCATE recusado', False, 'a tabela foi esvaziada')
        except Exception as exc:
            # Duas defesas: o papel da aplicação nem tem TRUNCATE (é como o
            # local e a produção conectam), e o gatilho recusa até o dono do
            # esquema — conferido à parte com `psql -U postgres`.
            conferir('TRUNCATE recusado', 'somente-insercao' in str(exc) or 'permission denied' in str(exc),
                     str(exc).splitlines()[0])
        conferir('a trilha continua com linhas', AuditEvent.objects.exists())
        from ai import review
        from documents import issuance

        fonte_review = inspect.getsource(review.reject_artifact)
        conferir('recusa da IA: o motivo fica no rascunho',
                 'artifact.motivo_recusa' in fonte_review and "'reason': reason" not in fonte_review)
        fonte_issuance = inspect.getsource(issuance)
        conferir('retificação: o motivo fica no documento, não no purpose',
                 'corrected.motivo_retificacao' in fonte_issuance
                 and "purpose=(reason or '')" not in fonte_issuance)

        print('=== 8. modelo pesado da instalação ===')
        from ai import providers, services as ai_services
        from ai.models import AIJobKind
        from base.models import InstallationSettings

        config = InstallationSettings.carregar()
        config.ai_model_pesado = 'modelo-pesado-de-teste'
        config.save(update_fields=['ai_model_pesado'])
        _, modelo_rapido, _ = config.ia_da_instalacao()
        _, modelo_pesado, _ = config.ia_da_instalacao(pesado=True)
        conferir('pesado=True devolve o modelo pesado', modelo_pesado == 'modelo-pesado-de-teste')
        conferir('e o padrão continua o rápido', modelo_rapido != 'modelo-pesado-de-teste')
        capturado = []
        with mock.patch.object(providers, '_build', lambda p, m, *a, **k: capturado.append((m, k.get('timeout')))), \
                mock.patch.object(providers, '_tenant_settings', lambda _t: None), \
                mock.patch.object(providers, 'installation_api_key', lambda _p: 'chave'), \
                mock.patch.object(dj_settings, 'AI_ENABLED', True):
            providers.get_chat_model(tenant_id=tenant.id)
            providers.get_chat_model(tenant_id=tenant.id, timeout=165, pesado=True)
        conferir('o chat vai ao modelo rápido', capturado and capturado[0][0] == modelo_rapido, capturado)
        conferir('a tarefa pesada vai ao pesado, com o prazo dela',
                 len(capturado) > 1 and capturado[1] == ('modelo-pesado-de-teste', 165), capturado)
        conferir('apoio diagnóstico e relatório são as tarefas pesadas',
                 ai_services.TAREFAS_PESADAS == {AIJobKind.DIAGNOSTIC_SUPPORT, AIJobKind.PATIENT_REPORT})
        conferir('o resumo do atendimento fica no rápido',
                 AIJobKind.ENCOUNTER_SUMMARY not in ai_services.TAREFAS_PESADAS)
        conferir('apoio diagnóstico com 150 s',
                 ai_services._limits_for(AIJobKind.DIAGNOSTIC_SUPPORT)['timeout_seconds'] == 150)
        conferir('run_job pede o pesado para as tarefas pesadas',
                 'pesado=job.kind in TAREFAS_PESADAS' in inspect.getsource(ai_services.run_job))
        conferir('o prazo de rede acompanha o da tarefa (PD-18)',
                 'installation_reserve_model(timeout=limite + 15)' in inspect.getsource(ai_services.run_job))

        print('=== 9. parcelamento segue o contrato ===')
        from tenancy import contract
        from tenancy.plans import CONTRATO_COM_PARCELAMENTO, parcelas_no_cartao, pricing

        abaixo = '0.1'
        conferir(f'abaixo da {CONTRATO_COM_PARCELAMENTO}: tudo à vista',
                 all(parcelas_no_cartao(p, abaixo) == 1 for p in ('anual', 'semestral', 'trimestral')))
        conferir(f'a partir da {CONTRATO_COM_PARCELAMENTO}: 12x, 6x e à vista',
                 [parcelas_no_cartao(p, CONTRATO_COM_PARCELAMENTO) for p in ('anual', 'semestral', 'trimestral')]
                 == [12, 6, 1])
        esperado = 12 if parcelas_no_cartao('anual', contract.VERSAO) > 1 else 1
        anual = next(p for p in pricing('complete')['periodos'] if p['code'] == 'anual')
        conferir(f'a vitrine segue o contrato vigente ({contract.VERSAO})', anual['parcelas'] == esperado,
                 anual['parcelas'])

        print('=== 10. TISS liberado ao contratar ===')
        from tenancy.services import liberar_tiss_pelo_plano

        conferir('Completo libera', liberar_tiss_pelo_plano(Tenant(plan='complete', tiss_liberado=False)))
        conferir('Básico não', not liberar_tiss_pelo_plano(Tenant(plan='basic', tiss_liberado=False)))
        conferir('já liberada: nada a fazer', not liberar_tiss_pelo_plano(Tenant(plan='complete', tiss_liberado=True)))

        from django.contrib.messages.storage.fallback import FallbackStorage

        from ops.superadmin import TenantPlanView

        operador = User.objects.filter(is_superuser=True).first() or usuario
        Tenant.objects.filter(id=tenant.id).update(
            plan='complete', tiss_liberado=False, tiss_nota='',
            degustacao_ate=timezone.now() + timedelta(days=3),
        )
        requisicao = fabrica.post(f'/instalacao/organizacoes/{tenant.id}/plano/', {
            'plan': 'complete', 'plan_note': 'Conversão da degustação (roteiro)',
        })
        requisicao.user = operador
        requisicao.session = {}
        requisicao._messages = FallbackStorage(requisicao)
        TenantPlanView().post(requisicao, tenant.id)
        tenant.refresh_from_db()
        conferir('converter a degustação no console libera o TISS', tenant.tiss_liberado, tenant.tiss_nota)
        conferir('e a degustação saiu de cena', tenant.degustacao_ate is None)
        conferir('a liberação está na trilha', AuditEvent.objects.filter(
            action='tenancy.tiss_liberado_pelo_plano', object_id=tenant.id,
            integrity_metadata__origem='console').exists())
        Tenant.objects.filter(id=tenant.id).update(tiss_liberado=False, tiss_nota='recolhido à mão')
        requisicao = fabrica.post('/x/', {'plan': 'complete', 'plan_note': 'Só os limites (roteiro)',
                                          'patient_limit_override': '1300'})
        requisicao.user = operador
        requisicao.session = {}
        requisicao._messages = FallbackStorage(requisicao)
        TenantPlanView().post(requisicao, tenant.id)
        tenant.refresh_from_db()
        conferir('Completo → Completo (só limites) não religa o TISS recolhido', not tenant.tiss_liberado)
        raise Desfazer
except Desfazer:
    print('=== transação desfeita: nada ficou na base ===')

if falhas:
    print(f'\n{len(falhas)} falha(s):')
    for f in falhas:
        print('  -', f)
    raise SystemExit(1)
print('\nOK: revisão de 2026-11-17 conferida.')
