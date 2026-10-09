"""Lote 1 da auditoria independente de 2026-10-09 (NeuroDoc 1.12.1).

Seis achados de segurança e de perda de dado, cada um pelo caminho que o
quebrava, contra o PostgreSQL de verdade. Detalhe e decisões em
`docs/homologation/auditoria-1.12.1.md`.

1. **ND-1121-001** -- o PDF de documento médico: a recepção imprime o
   **emitido**, não abre o **rascunho**, ninguém o remove pela lista de
   anexos, e a coleta de arquivos não o apaga; a migração reclassifica o
   referenciado e o rascunho órfão;
2. **ND-1121-002** -- finalizar não grava por cima do texto salvo por
   outra requisição;
3. **ND-1121-003** -- o reenvio para e-mail **e** SMS deixa os dois links
   novos vivos, e o antigo morto;
4. **ND-1121-010** -- o `next` depois do MFA não sai do domínio;
5. **ND-1121-017** -- o formulário do portal aberto para um paciente não
   grava na ficha de outro identificado depois;
6. **ND-1121-016** -- a mesma entrega não sai duas vezes.
"""
import importlib
import inspect
import secrets
from datetime import timedelta
from pathlib import Path

from django.conf import settings as dj_settings
from django.test import Client, RequestFactory

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.apps import apps as django_apps
from django.core.cache import cache
from django.utils import timezone

from accounts.models import User
from communications import access, services
from communications.models import (
    Delivery, DeliveryAttempt, DeliveryChannel, DeliveryStatus, DocumentAccessToken,
)
from documents.models import (
    Attachment, AttachmentClassification, DocumentRequest,
    MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus,
)
from documents.storage import store_generated_attachment
from patients.models import Patient, PatientContact, PatientStatus, RegistrationStage
from tenancy.models import ClinicProfile, Membership, Tenant

failures = []
raiz = Path(dj_settings.BASE_DIR)
SUFIXO = secrets.token_hex(3)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


def logado(email, tenant):
    c = Client()
    c.force_login(User.objects.get(email=email))
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s.save()
    return c


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(tenant=tenant, user__email='doctor-a@demo.neurodoc.local').first()
secretaria = logado('secretary-a@demo.neurodoc.local', tenant)
doutora = logado('doctor-a@demo.neurodoc.local', tenant)

criados = {'pacientes': [], 'documentos': [], 'anexos': [], 'contatos': [], 'pedidos': []}

try:
    paciente = Patient.objects.create(
        tenant=tenant, full_name=f'PACIENTE DO LOTE UM {SUFIXO}',
        registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(paciente.id)

    print('=== 1. ND-1121-001: o PDF do documento medico ===')
    confere(inspect.signature(store_generated_attachment).parameters['classification'].default
            == AttachmentClassification.CLINICAL,
            'PDF gerado nasce clinico')

    def documento_com_pdf(status, classificacao=AttachmentClassification.CLINICAL):
        doc = MedicalDocument.objects.create(
            tenant=tenant, patient=paciente, physician=medico,
            kind=MedicalDocumentKind.REPORT, status=status,
            document_number=f'REL-L1-{SUFIXO}-{len(criados["documentos"])}',
            content_snapshot={'report_text': 'Relatorio do roteiro.'},
            validation_token=secrets.token_urlsafe(16),
        )
        pdf = store_generated_attachment(
            tenant, paciente, medico.user, b'%PDF-1.4 roteiro ' + secrets.token_bytes(8),
            f'report_{doc.id}_papel.pdf', classification=classificacao,
        )
        doc.pdf_attachment = pdf
        doc.save(update_fields=['pdf_attachment'])
        criados['documentos'].append(doc.id)
        criados['anexos'].append(pdf.id)
        return doc, pdf

    emitido, pdf_emitido = documento_com_pdf(MedicalDocumentStatus.ISSUED_ON_PAPER)
    rascunho, pdf_rascunho = documento_com_pdf(MedicalDocumentStatus.DRAFT)

    from django.urls import reverse

    baixar = lambda a: reverse('documents:download', args=[a.id])  # noqa: E731
    remover = lambda a: reverse('documents:delete', args=[a.id])  # noqa: E731
    lista = reverse('documents:list', args=[paciente.id])

    confere(secretaria.get(baixar(pdf_emitido)).status_code == 200,
            'a secretaria baixa a receita/relatorio EMITIDO para imprimir')
    confere(secretaria.get(baixar(pdf_rascunho)).status_code == 404,
            'e nao abre o RASCUNHO, que e conteudo clinico ainda nao liberado')
    confere(doutora.get(baixar(pdf_rascunho)).status_code == 200,
            'a medica abre o rascunho -- senao a secao mede o nada')
    corpo = secretaria.get(lista).content.decode()
    confere(pdf_emitido.original_name in corpo, 'na lista, a secretaria ve o nome do emitido')
    confere(pdf_rascunho.original_name not in corpo, 'e nao ve o nome do rascunho')
    confere(remover(pdf_emitido) not in corpo and remover(pdf_rascunho) not in corpo,
            'e nao ve botao de remover em PDF de documento')
    corpo_medica = doutora.get(lista).content.decode()
    confere(remover(pdf_emitido) not in corpo_medica,
            'nem a medica remove o PDF do documento pela lista de anexos')

    for quem, cliente in (('secretaria', secretaria), ('medica', doutora)):
        cliente.post(remover(pdf_emitido))
        pdf_emitido.refresh_from_db()
        confere(pdf_emitido.deleted_at is None, f'o POST montado a mao pela {quem} e recusado')

    # A coleta: um PDF de documento excluido antes desta correcao, ainda
    # administrativo, envelhecido alem dos 30 dias.
    velho, pdf_velho = documento_com_pdf(MedicalDocumentStatus.ISSUED,
                                         AttachmentClassification.ADMINISTRATIVE)
    Attachment.objects.filter(id=pdf_velho.id).update(deleted_at=timezone.now() - timedelta(days=90))
    from documents.retention import garbage_collect

    removidos, retidos = garbage_collect(dry_run=True)
    confere(pdf_velho.id not in removidos and pdf_velho.id in retidos,
            'a coleta retem o PDF de documento mesmo excluido e administrativo')

    # A migracao de dados: referenciado e rascunho orfao.
    Attachment.objects.filter(id=pdf_velho.id).update(deleted_at=None)
    orfao = store_generated_attachment(
        tenant, paciente, medico.user, b'%PDF-1.4 orfao ' + secrets.token_bytes(8),
        f'report_{velho.id}_draft.pdf', classification=AttachmentClassification.ADMINISTRATIVE,
    )
    criados['anexos'].append(orfao.id)
    upload = store_generated_attachment(
        tenant, paciente, medico.user, b'%PDF-1.4 upload ' + secrets.token_bytes(8),
        'carteirinha_convenio.pdf', classification=AttachmentClassification.ADMINISTRATIVE,
    )
    criados['anexos'].append(upload.id)
    migracao = importlib.import_module('documents.migrations.0007_pdf_de_documento_e_clinico')
    migracao.classificar(django_apps, None)
    for anexo, esperado, nome in ((pdf_velho, 'clinical', 'o referenciado'),
                                  (orfao, 'clinical', 'o rascunho orfao'),
                                  (upload, 'administrative', 'o upload administrativo')):
        anexo.refresh_from_db()
        confere(anexo.classification == esperado, f'migracao: {nome} fica {esperado}', anexo.classification)

    print('=== 2. ND-1121-002: finalizar nao apaga o que outra aba salvou ===')
    from clinical import finalization
    from clinical.models import Encounter, EncounterKind, EncounterStatus

    atendimento = Encounter.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        kind=EncounterKind.FREE_TEXT, occurred_at=timezone.now(),
        free_text='texto antigo', plan_text='conduta',
    )
    copia_velha = Encounter.objects.get(id=atendimento.id)
    Encounter.objects.filter(id=atendimento.id).update(
        free_text='texto NOVO do autosave', row_version=atendimento.row_version + 1,
    )
    from tenancy.context import AccessContext
    import uuid as _uuid

    ctx = AccessContext(user_id=medico.user_id, tenant_id=tenant.id, membership_id=medico.id,
                        permissions=frozenset(), request_id=_uuid.uuid4())
    devolvido = finalization.finalize_encounter(ctx, copia_velha, medico)
    atendimento.refresh_from_db()
    confere(atendimento.status == EncounterStatus.FINALIZED, 'o atendimento finalizou')
    confere(atendimento.free_text == 'texto NOVO do autosave',
            'com o texto que o autosave gravou, e nao o da copia velha', atendimento.free_text)
    confere(atendimento.content_hash == atendimento.compute_content_hash(),
            'e o hash sela o texto que de fato ficou')
    confere(devolvido.free_text == 'texto NOVO do autosave',
            'a funcao devolve a linha do banco, para a view seguir com ela')
    criados['atendimento'] = atendimento.id

    print('=== 3. ND-1121-003: reenvio para e-mail e SMS ===')
    agora = timezone.now()
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name=paciente.full_name,
        email=f'lote1.{SUFIXO}@example.invalid', phone='11988887777',
        verified_email_at=agora, verified_phone_at=agora,
        authorized_for_documents=True, email_enabled=True, sms_enabled=True,
    )
    criados['contatos'].append(contato.id)
    antigo, _ = access.create_access_token(emitido, contato)
    enviados = []
    original = (services.send_email, services.send_sms)
    services.send_email = lambda *a, **k: enviados.append('email')
    services.send_sms = lambda *a, **k: enviados.append('sms') or {'id': f'roteiro-{len(enviados)}'}
    try:
        entregas = services.deliver_document(emitido, force_new_link=True)
    finally:
        services.send_email, services.send_sms = original
    confere(sorted(enviados) == ['email', 'sms'], 'saiu uma mensagem por canal', str(enviados))
    vivos = DocumentAccessToken.objects.filter(document=emitido, revoked_at__isnull=True)
    confere(vivos.count() == 2, 'os DOIS links novos continuam valendo', str(vivos.count()))
    antigo.refresh_from_db()
    confere(antigo.revoked_at is not None, 'e o link de antes do reenvio foi revogado')

    print('=== 4. ND-1121-010: o next depois do MFA ===')
    from accounts import views as acc_views

    req = RequestFactory().get('/accounts/mfa/?next=https://golpe.example.invalid/')
    confere(acc_views._safe_next(req) is None, '_safe_next recusa dominio externo')
    req = RequestFactory().get('/accounts/mfa/?next=/app/')
    confere(acc_views._safe_next(req) == '/app/', 'e aceita o caminho interno')
    fonte = inspect.getsource(acc_views.MFAChallengeView.form_valid)
    confere("GET.get('next')" not in fonte and '_safe_next(' in fonte,
            'a conclusao do MFA usa _safe_next')
    confere('Invalid code' not in fonte, 'e o erro do codigo sai em portugues')

    print('=== 5. ND-1121-017: formulario do portal de outra identificacao ===')
    perfil = ClinicProfile.objects.get_or_create(tenant=tenant)[0]
    guardado = (perfil.patient_portal_enabled, perfil.patient_portal_requires_recent_visit)
    perfil.patient_portal_enabled = True
    perfil.patient_portal_requires_recent_visit = False
    perfil.save()
    try:
        import random
        from datetime import date

        def cpf_valido():
            base = [random.randint(0, 9) for _ in range(9)]
            for tamanho in (9, 10):
                soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(base[:tamanho]))
                base.append((soma * 10 % 11) % 10)
            return ''.join(map(str, base))

        # Dois irmaos: o caso real e o de quem pede por duas pessoas no
        # mesmo navegador.
        com_cpf = []
        for nome, nasc in (('PRIMEIRO', date(2015, 3, 4)), ('SEGUNDO', date(2017, 8, 9))):
            irmao = Patient.objects.create(
                tenant=tenant, full_name=f'{nome} IRMAO {SUFIXO}', cpf=cpf_valido(),
                birth_date=nasc, registration_stage=RegistrationStage.COMPLETE,
            )
            criados['pacientes'].append(irmao.id)
            com_cpf.append(irmao)
        if True:
            a, b = com_cpf
            cache.delete('portal:lookup:127.0.0.1')
            navegador = Client()

            def identifica(p):
                navegador.post(f'/solicitacoes/{tenant.slug}/', {
                    'cpf': p.cpf, 'birth_date': p.birth_date.isoformat(), 'privacy_ack': '1'})
                return navegador.session['portal_patient']['token']

            token_a = identifica(a)
            corpo = navegador.get(f'/solicitacoes/{tenant.slug}/solicitar/').content.decode()
            confere(token_a in corpo, 'o formulario leva o token da identificacao que o abriu')
            identifica(b)  # outra aba
            pedido = {
                'kind': 'prescription_simple', 'requester': 'self', 'identidade': token_a,
                'med_name': f'Remedio de A {SUFIXO}', 'med_dose': '1 mg', 'med_usage': '1 cp',
            }
            r = navegador.post(f'/solicitacoes/{tenant.slug}/solicitar/', pedido)
            confere(r.status_code == 409, 'o formulario de A e recusado com 409', str(r.status_code))
            confere(not DocumentRequest.objects.filter(
                tenant=tenant, patient=b, created_at__gte=agora).exists(),
                'e nada e gravado na ficha de B')
            confere(b.full_name.split(' ')[0] in r.content.decode(),
                    'a tela diz para quem o pedido sera feito agora')
            pedido['identidade'] = navegador.session['portal_patient']['token']
            r = navegador.post(f'/solicitacoes/{tenant.slug}/solicitar/', pedido)
            feito = DocumentRequest.objects.filter(tenant=tenant, patient=b, created_at__gte=agora)
            criados['pedidos'].extend(feito.values_list('id', flat=True))
            confere(feito.exists(), 'com o token de agora, o pedido entra -- controle positivo')
    finally:
        perfil.patient_portal_enabled, perfil.patient_portal_requires_recent_visit = guardado
        perfil.save()
        cache.delete('portal:lookup:127.0.0.1')

    print('=== 6. ND-1121-016: a mesma entrega nao sai duas vezes ===')
    entrega = Delivery.objects.create(
        tenant=tenant, document=emitido, contact=contato, channel=DeliveryChannel.EMAIL,
        event_version=1, idempotency_key=f'roteiro-lote1:{SUFIXO}',
    )
    copia = Delivery.objects.get(id=entrega.id)
    envios = []

    def transporte(*a, **k):
        envios.append(1)
        if len(envios) == 1:
            # Enquanto o primeiro fala com o provedor, um segundo
            # consumidor -- o do lease retomado -- tenta a mesma entrega.
            services._send(copia, 'mensagem')

    original = services.send_email
    services.send_email = transporte
    try:
        services._send(entrega, 'mensagem')
    finally:
        services.send_email = original
    entrega.refresh_from_db()
    confere(len(envios) == 1, 'um envio so, com dois consumidores na mesma entrega', str(len(envios)))
    confere(entrega.status == DeliveryStatus.ACCEPTED, 'e a entrega termina aceita', entrega.status)

    falha = Delivery.objects.create(
        tenant=tenant, document=emitido, contact=contato, channel=DeliveryChannel.EMAIL,
        event_version=1, idempotency_key=f'roteiro-lote1-falha:{SUFIXO}',
    )

    def transporte_quebrado(*a, **k):
        raise services.EmailSendFailed('roteiro')

    services.send_email = transporte_quebrado
    try:
        services._send(falha, 'mensagem')
    finally:
        services.send_email = original
    falha.refresh_from_db()
    confere(falha.status == DeliveryStatus.PENDING,
            'falha de transporte devolve a entrega a fila, reenviavel como antes', falha.status)

finally:
    DeliveryAttempt.objects.filter(delivery__contact_id__in=criados['contatos']).delete()
    Delivery.objects.filter(contact_id__in=criados['contatos']).delete()
    DocumentAccessToken.objects.filter(document_id__in=criados['documentos']).delete()
    DocumentRequest.objects.filter(patient_id__in=criados['pacientes']).delete()
    PatientContact.objects.filter(id__in=criados['contatos']).delete()
    if criados.get('atendimento'):
        from clinical.models import Encounter

        Encounter.objects.filter(id=criados['atendimento']).delete()
    MedicalDocument.objects.filter(id__in=criados['documentos']).update(
        pdf_attachment=None, signed_pdf_attachment=None)
    MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
    Attachment.objects.filter(id__in=criados['anexos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - o lote 1 da auditoria se sustenta.')
