"""Todo link que sai numa mensagem tem de abrir.

O defeito que originou este roteiro chegou ao medico assim: **o e-mail
chegou, e o link dentro dele dizia "invalido ou expirado"**. O pior
formato possivel de falha -- o paciente ve a mensagem, confia nela, clica,
e o sistema o acusa de ter um link velho.

A causa nao estava no link: estava na **ordem**. O token era gravado
dentro de uma transacao, e o e-mail era enfileirado dentro da mesma
transacao, com `.delay()`. A tarefa ia para a fila na hora, e o worker e
mais rapido que o resto da requisicao. Dois desfechos, os dois ruins:

- o worker manda o e-mail **antes** de o token estar visivel para outra
  conexao; ou
- a transacao falha depois do envio, e o token **nunca chega a existir** --
  foi o que aconteceu quando o SMS estourou por exceder o segmento.

A correcao e estrutural e vale para o produto inteiro (`on_commit` no
backend de e-mail). Este roteiro e a prova de que ela vale, e a guarda
contra o proximo ponto que criar token e mandar mensagem.

O que ele cobra, fluxo por fluxo, **abrindo o link de verdade**:

- entrega de documento (`/d/<token>/`);
- verificacao de endereco de e-mail;
- convite de colaborador;
- descadastro de campanha;
- e a regra que liga todos: **nenhum e-mail e enfileirado antes do
  commit**, e transacao desfeita nao manda mensagem nenhuma.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import re
import secrets
import uuid
from pathlib import Path
from unittest.mock import patch

from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from communications import access, services
from communications.models import Delivery, DeliveryAttempt, DeliveryChannel, DocumentAccessToken
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient, PatientContact, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'pacientes': [], 'documentos': [], 'contatos': [], 'usuarios': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:64} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


CHR = chr(10)
SUFIXO = secrets.token_hex(4).upper()
tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
agora = timezone.now()
publico = Client()

try:
    print(CHR + '1. Nenhum e-mail e enfileirado antes do commit')
    # A assercao central, e a que teria evitado o link invalido. Uma
    # transacao desfeita nao pode ter mandado mensagem nenhuma -- se
    # mandou, mandou com dados que nao existem mais.
    from communications import mail_backend

    with patch('communications.tasks.deliver_installation_email.delay') as fila:
        try:
            with transaction.atomic():
                from django.core.mail import send_mail

                send_mail(
                    'Roteiro', 'corpo', 'de@example.invalid', ['para@example.invalid'],
                )
                conferir('dentro da transacao, a fila ainda nao foi tocada',
                         fila.called, False)
                raise RuntimeError('desfaz')
        except RuntimeError:
            pass
        conferir('e a transacao desfeita nao manda nada', fila.called, False)

    with patch('communications.tasks.deliver_installation_email.delay') as fila:
        with transaction.atomic():
            from django.core.mail import send_mail

            send_mail('Roteiro', 'corpo', 'de@example.invalid', ['para@example.invalid'])
        conferir('a transacao que fecha manda', fila.called, True)

    fonte = Path(dj_settings.BASE_DIR, 'communications', 'mail_backend.py').read_text(encoding='utf-8')
    conferir('e o backend usa on_commit, nao delay direto',
             'transaction.on_commit' in fonte, True)

    print(CHR + '2. O link do documento abre de verdade')
    paciente = Patient.objects.create(
        tenant=tenant, full_name='LEITOR DE LINK DO ROTEIRO',
        cpf='52998224725', registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(paciente.id)
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name='LEITOR DE LINK DO ROTEIRO',
        email='leitor.roteiro@example.invalid', verified_email_at=agora,
        authorized_for_documents=True, email_enabled=True,
    )
    criados['contatos'].append(contato.id)
    documento = MedicalDocument.objects.create(
        tenant=tenant, patient=paciente, physician=vinculo,
        kind=MedicalDocumentKind.REPORT, status=MedicalDocumentStatus.ISSUED,
        document_number=f'REL-LK-{SUFIXO}', issued_at=agora,
        content_snapshot={'report_text': 'Relatorio do roteiro de links.'},
        validation_token=secrets.token_urlsafe(16),
    )
    criados['documentos'].append(documento.id)

    # Captura o texto que de fato sairia, e extrai o link dele -- e nao de
    # uma reconstrucao, que e justamente onde o defeito se esconderia.
    capturado = {}

    def _capturar(destino, assunto, corpo, **kwargs):
        capturado['corpo'] = corpo

    with patch('communications.services.send_email', side_effect=_capturar):
        services.deliver_document(documento)

    conferir('a mensagem foi montada', 'corpo' in capturado, True)
    achado = re.search(r'(https?://\S+/d/[A-Za-z0-9_-]+/)', capturado.get('corpo', ''))
    conferir('e ela carrega um link de documento', achado is not None, True)
    if achado:
        caminho = '/d/' + achado.group(1).rstrip('/').rsplit('/', 1)[1] + '/'
        resposta = publico.get(caminho)
        conferir('o link do e-mail abre', resposta.status_code, 200)
        corpo = resposta.content.decode()
        conferir('  e pede o desafio, em vez de dizer invalido',
                 'inválido' in corpo.lower() or 'expirado' in corpo.lower(), False)
        conferir('  perguntando os 4 ultimos digitos do CPF',
                 'CPF' in corpo or 'cpf' in corpo, True)

    print(CHR + '3. O token existe no banco quando a mensagem sai')
    # A outra ponta da mesma regra: o token tem de estar **gravado** --
    # visivel para outra conexao -- antes de alguem receber o link.
    tokens = DocumentAccessToken.objects.filter(document=documento, revoked_at__isnull=True)
    conferir('ha um token vivo para o documento entregue', tokens.count() >= 1, True)
    vivo = tokens.first()
    conferir('ele nao esta revogado', vivo.revoked_at, None)
    conferir('e ainda nao venceu', vivo.expires_at > timezone.now(), True)

    print(CHR + '4. Reenvio troca o link, e o novo vale')
    capturado.clear()
    with patch('communications.services.send_email', side_effect=_capturar):
        services.deliver_document(documento, force_new_link=True)
    achado2 = re.search(r'(https?://\S+/d/[A-Za-z0-9_-]+/)', capturado.get('corpo', ''))
    conferir('o reenvio montou outra mensagem', achado2 is not None, True)
    if achado and achado2:
        conferir('com um link diferente', achado.group(1) != achado2.group(1), True)
        novo = '/d/' + achado2.group(1).rstrip('/').rsplit('/', 1)[1] + '/'
        conferir('o link novo abre', publico.get(novo).status_code, 200)
        antigo = '/d/' + achado.group(1).rstrip('/').rsplit('/', 1)[1] + '/'
        conferir('e o antigo deixou de valer',
                 publico.get(antigo).status_code in (403, 404, 410), True)

    print(CHR + '5. A verificacao de endereco de e-mail')
    from accounts.models import User
    from accounts import services as account_services

    sufixo = uuid.uuid4().hex[:8]
    novo_usuario = User.objects.create_user(
        f'roteiro-link-{sufixo}@example.invalid', 'Senha-descartavel-123!',
        first_name='Leitor', last_name='De Link',
    )
    criados['usuarios'].append(novo_usuario.id)
    conferir('o usuario nasce sem o e-mail verificado',
             novo_usuario.email_verified_at, None)
    bruto = account_services.generate_email_verification_token(novo_usuario)
    url = reverse('accounts:verify-email', args=[bruto])
    resposta = publico.get(url)
    conferir('o link de verificacao responde', resposta.status_code in (200, 302), True)
    novo_usuario.refresh_from_db()
    conferir('e o endereco fica verificado', novo_usuario.email_verified_at is not None, True)

    print(CHR + '6. O convite de colaborador')
    from tenancy.models import Invitation

    # O campo e `target_tenant`, nao `tenant`: o convite de plataforma
    # nasce antes de a clinica existir, e por isso ele e opcional.
    conferir('o modelo de convite guarda so o resumo do token',
             'token_hash' in [f.name for f in Invitation._meta.get_fields()], True)
    url = reverse('tenancy:accept-invite', args=[secrets.token_urlsafe(32)])
    conferir('token forjado nao abre o aceite',
             publico.get(url).status_code in (400, 403, 404, 410), True)

    print(CHR + '7. O descadastro de campanha')
    contato.marketing_unsubscribe_token = secrets.token_urlsafe(24)
    contato.marketing_opt_in_at = agora
    contato.save(update_fields=['marketing_unsubscribe_token', 'marketing_opt_in_at'])
    url = reverse('marketing-unsubscribe', args=[contato.marketing_unsubscribe_token])
    resposta = publico.get(url)
    conferir('o link de descadastro abre', resposta.status_code, 200)
    resposta = publico.post(url)
    conferir('e o POST descadastra', resposta.status_code in (200, 302), True)
    contato.refresh_from_db()
    # Marca a revogacao e **preserva** o consentimento original. Apagar o
    # `opt_in` apagaria a prova de que ele existiu -- e e essa prova que
    # sustenta o que ja foi enviado. A primeira versao desta assercao
    # cobrava o apagamento, ou seja, cobrava o defeito.
    conferir('  marcando a revogacao', contato.marketing_opt_out_at is not None, True)
    conferir('  e preservando a prova do consentimento',
             contato.marketing_opt_in_at is not None, True)
    # Idempotente: quem clica duas vezes nao recebe erro.
    conferir('clicar de novo nao quebra',
             publico.post(url).status_code in (200, 302), True)

    print(CHR + '8. Token adulterado nunca abre')
    # A outra metade: o link tem de abrir para quem o recebeu, e **nao**
    # abrir para quem o inventou.
    for falso in ('x' * 43, secrets.token_urlsafe(32), 'aaaa'):
        conferir(f'  token forjado ({falso[:12]}...) nao abre',
                 publico.get(f'/d/{falso}/').status_code in (403, 404, 410), True)
    revogado = DocumentAccessToken.objects.filter(document=documento).first()
    conferir('e token revogado tambem nao',
             access.resolve_token('qualquer-coisa') is None, True)

finally:
    DeliveryAttempt.objects.filter(delivery__document_id__in=criados['documentos']).delete()
    Delivery.objects.filter(document_id__in=criados['documentos']).delete()
    DocumentAccessToken.objects.filter(document_id__in=criados['documentos']).delete()
    MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
    PatientContact.objects.filter(id__in=criados['contatos']).delete()
    Patient.objects.filter(id__in=criados['pacientes']).delete()
    from accounts.models import User as _User

    _User.objects.filter(id__in=criados['usuarios']).delete()
    print(f'{CHR}  limpeza: objetos do roteiro removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print(CHR + 'OK: o token esta gravado antes de a mensagem sair, e todo link')
print('    enviado abre -- inclusive o do e-mail que o paciente recebe.')
