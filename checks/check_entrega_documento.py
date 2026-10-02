"""Entrega do documento ao paciente: automatica, e que nao derruba a tela.

O defeito que originou este roteiro chegou como `Server Error (500)` na
tela, com o documento **ja assinado** -- o pior momento possivel para uma
falha, porque a parte irreversivel ja aconteceu.

A causa tinha tres camadas, e cada uma sozinha ja era um defeito:

1. **A mensagem nao cabia no SMS.** O mesmo texto servia aos dois canais:
   no e-mail ficava bem e no SMS dava **221 caracteres** contra um limite
   de 160. Nunca coube -- so nao aparecia porque os pacientes anteriores
   tinham apenas e-mail cadastrado.
2. **O erro era `ValueError`, que ninguem trata.** Subiu por `_send`, por
   `deliver_document` e pela view ate virar a tela de erro.
3. **A transacao envolvia todos os canais.** O `rollback` levou junto a
   linha do e-mail ja aceito: o paciente nao recebeu nada, e a lista de
   entregas nao mostrava sequer a tentativa.

O que este roteiro cobra:

- a mensagem de SMS cabe num segmento **com o link real**, e nao por
  contagem feita a mao -- `PUBLIC_BASE_URL` muda por instalacao;
- a de e-mail continua completa e acentuada: la nao ha limite;
- **o e-mail sai mesmo com o SMS quebrado**, que e a assercao que teria
  evitado o estrago;
- falha inesperada vira entrega marcada como falha, nunca excecao solta;
- a entrega sai pelo **worker**: `app` nao tem saida para a internet, e o
  SMS feito dentro da requisicao so pode terminar em timeout;
- o envio e **automatico** na emissao, por evento -- o botao da tela e
  reenvio, nao o primeiro envio;
- o SMS segue o plano, e o e-mail vale para todos.
"""
from datetime import timedelta

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

import secrets
from pathlib import Path
from unittest.mock import patch

from django.utils import timezone

from communications import services
from communications.models import Delivery, DeliveryChannel, DeliveryStatus
from communications.smsdev import SmsSendFailed
from documents.models import MedicalDocument, MedicalDocumentKind, MedicalDocumentStatus
from patients.models import Patient, PatientContact, RegistrationStage
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []
criados = {'pacientes': [], 'documentos': [], 'contatos': []}


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:64} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


CHR = chr(10)
# Numero unico por execucao: `UNIQUE(tenant, document_number)` nao
# perdoa, e uma rodada que morra antes da limpeza deixaria a seguinte
# falhando por colisao -- erro do roteiro parecendo erro do produto.
SUFIXO = secrets.token_hex(4).upper()
tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()

try:
    print(CHR + '1. A mensagem de SMS cabe num segmento, com o link real')
    # A contagem e feita com o link que o sistema monta de fato: o token e
    # `secrets.token_urlsafe(32)` e a base vem de `PUBLIC_BASE_URL`, que
    # muda por instalacao. Uma contagem fixa quebraria na primeira que
    # tivesse um dominio mais longo.
    link_real = f'{dj_settings.PUBLIC_BASE_URL}/d/{secrets.token_urlsafe(32)}/'
    sms = services._document_message(None, link_real, DeliveryChannel.SMS)
    conferir(f'a mensagem tem {len(sms)} caracteres (limite {services.SMS_SEGMENTO})',
             len(sms) <= services.SMS_SEGMENTO, True)
    conferir('e o link inteiro esta nela', link_real in sms, True)
    conferir('e ela pede os 4 ultimos digitos do CPF', 'CPF' in sms, True)

    # Sem acento: basta um para a operadora passar a mensagem a UCS-2, e o
    # segmento cair de 160 para 70 -- com um link de 70 caracteres, nada
    # caberia.
    acentos = [c for c in sms if c in 'áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ']
    conferir('o SMS nao leva acento (GSM-7, 160 e nao 70)', acentos, [])

    # E com um dominio bem mais longo, cai na versao minima e continua
    # cabendo.
    link_longo = f'https://prontuario.clinica-de-neurologia-exemplo.com.br/d/{secrets.token_urlsafe(32)}/'
    sms_longo = services._document_message(None, link_longo, DeliveryChannel.SMS)
    conferir('com dominio longo, ainda cabe',
             len(sms_longo) <= services.SMS_SEGMENTO, True)
    conferir('  e o link continua inteiro', link_longo in sms_longo, True)

    print(CHR + '2. O e-mail continua completo e acentuado')
    email = services._document_message(None, link_real, DeliveryChannel.EMAIL)
    conferir('o e-mail e mais longo que o SMS', len(email) > len(sms), True)
    conferir('e mantem o portugues com acento',
             any(c in email for c in 'áéíóúâêôãõç'), True)
    conferir('e nao foi encurtado pelo limite de SMS',
             len(email) > services.SMS_SEGMENTO, True)

    print(CHR + '3. A mensagem que estourava: 221 caracteres')
    # A assercao nomeada do defeito. Se alguem voltar a usar um texto so
    # para os dois canais, isto reprova.
    antiga = (
        f'{services.DOCUMENT_MESSAGE} {link_real} '
        'Para abrir, informe os 4 últimos dígitos do CPF do paciente.'
    )
    conferir(f'o texto antigo tinha {len(antiga)} caracteres e nao cabia',
             len(antiga) > services.SMS_SEGMENTO, True)
    conferir('e o novo cabe', len(sms) <= services.SMS_SEGMENTO, True)

    print(CHR + '4. O e-mail sai mesmo com o SMS quebrado')
    # A assercao que teria evitado o estrago inteiro.
    paciente = Patient.objects.create(
        tenant=tenant, full_name='DESTINATARIO DO ROTEIRO',
        registration_stage=RegistrationStage.COMPLETE,
    )
    criados['pacientes'].append(paciente.id)
    agora = timezone.now()
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name='DESTINATARIO DO ROTEIRO',
        email='destinatario.roteiro@example.invalid', phone='11988887777',
        verified_email_at=agora, verified_phone_at=agora,
        authorized_for_documents=True, email_enabled=True, sms_enabled=True,
    )
    criados['contatos'].append(contato.id)
    documento = MedicalDocument.objects.create(
        tenant=tenant, patient=paciente, physician=vinculo,
        kind=MedicalDocumentKind.REPORT, status=MedicalDocumentStatus.ISSUED,
        document_number=f'REL-RT-{SUFIXO}-1', issued_at=agora,
        content_snapshot={'report_text': 'Relatorio do roteiro.'},
        validation_token=secrets.token_urlsafe(16),
    )
    criados['documentos'].append(documento.id)

    with patch('communications.services.send_sms', side_effect=SmsSendFailed('quebrado')), \
            patch('communications.services.send_email') as email_mock:
        entregas = services.deliver_document(documento)

    por_canal = {d.channel: d for d in entregas}
    conferir('os dois canais produziram uma entrega', len(entregas), 2)
    conferir('o e-mail foi chamado', email_mock.called, True)
    conferir('a entrega de e-mail existe', DeliveryChannel.EMAIL in por_canal, True)
    if DeliveryChannel.EMAIL in por_canal:
        conferir('  e foi aceita apesar do SMS quebrado',
                 por_canal[DeliveryChannel.EMAIL].status, DeliveryStatus.ACCEPTED)
    conferir('a entrega de SMS existe e aparece como pendente/falha',
             por_canal[DeliveryChannel.SMS].status != DeliveryStatus.ACCEPTED, True)
    conferir('e as duas ficaram gravadas no banco',
             Delivery.objects.filter(tenant=tenant, document=documento).count(), 2)

    print(CHR + '5. Falha inesperada nao vira tela de erro')
    # A rede final de `_send`. Qualquer excecao que nao seja das esperadas
    # tem de virar entrega marcada como falha -- nunca subir.
    documento2 = MedicalDocument.objects.create(
        tenant=tenant, patient=paciente, physician=vinculo,
        kind=MedicalDocumentKind.REPORT, status=MedicalDocumentStatus.ISSUED,
        document_number=f'REL-RT-{SUFIXO}-2', issued_at=agora,
        content_snapshot={'report_text': 'Outro.'},
        validation_token=secrets.token_urlsafe(16),
    )
    criados['documentos'].append(documento2.id)
    estourou = False
    try:
        with patch('communications.services.send_sms', side_effect=ValueError('erro nosso')), \
                patch('communications.services.send_email'):
            entregas2 = services.deliver_document(documento2)
    except Exception:
        estourou = True
    conferir('a entrega nao propaga a excecao', estourou, False)
    if not estourou:
        sms2 = next((d for d in entregas2 if d.channel == DeliveryChannel.SMS), None)
        conferir('o SMS fica marcado como falha', sms2.status, DeliveryStatus.FAILED)
        email2 = next((d for d in entregas2 if d.channel == DeliveryChannel.EMAIL), None)
        conferir('e o e-mail continua aceito', email2.status, DeliveryStatus.ACCEPTED)

    print(CHR + '6. `send_sms` nao levanta mais erro cru')
    from communications import smsdev

    tipo = None
    try:
        smsdev.send_sms('11988887777', 'x' * 200, refer='roteiro')
    except SmsSendFailed:
        tipo = 'SmsSendFailed'
    except ValueError:
        tipo = 'ValueError'
    except Exception as exc:
        tipo = exc.__class__.__name__
    conferir('mensagem longa vira SmsSendFailed, que o chamador trata',
             tipo in ('SmsSendFailed', 'SmsChannelDisabled'), True)
    conferir('  e nao ValueError, que ninguem trata', tipo == 'ValueError', False)

    print(CHR + '7. A entrega sai pelo worker, nao dentro da requisicao')
    # `app` nao tem saida para a internet (ver `communications/mail_backend.py`).
    # O e-mail escapava porque o backend dele enfileira sozinho; o SMS nao.
    views = Path(dj_settings.BASE_DIR, 'documents', 'views.py').read_text(encoding='utf-8')
    inicio = views.index('class MedicalDocumentSendView')
    corpo = views[inicio:views.index('class MedicalDocumentReviewView')]
    conferir('a view de reenvio enfileira a tarefa',
             'deliver_document_task' in corpo, True)
    conferir('  usando .delay (vai para o worker)', '.delay(' in corpo, True)
    conferir('e nao chama a entrega direto na requisicao',
             'deliver_document(document' in corpo, False)

    tarefas = Path(dj_settings.BASE_DIR, 'communications', 'tasks.py').read_text(encoding='utf-8')
    conferir('a tarefa existe', 'def deliver_document_task' in tarefas, True)

    print(CHR + '8. O envio e automatico na emissao')
    # O botao da tela e reenvio. O primeiro envio nasce do evento emitido
    # por `sign_and_issue` e consumido por `communications.handlers`.
    issuance = Path(dj_settings.BASE_DIR, 'documents', 'issuance.py').read_text(encoding='utf-8')
    conferir('assinar emite o evento de documento emitido',
             'DOCUMENT_ISSUED_TOPIC' in issuance and 'OutboxEvent.objects.get_or_create' in issuance, True)
    apps_comm = Path(dj_settings.BASE_DIR, 'communications', 'apps.py').read_text(encoding='utf-8')
    conferir('e o consumidor da entrega esta registrado nesse topico',
             "register_handler('documents.document_issued'" in apps_comm, True)
    handlers = Path(dj_settings.BASE_DIR, 'communications', 'handlers.py').read_text(encoding='utf-8')
    conferir('  e ele entrega o documento', 'deliver_document(document)' in handlers, True)

    print(CHR + '9. O SMS segue o plano; o e-mail vale para todos')
    from tenancy.plans import has_sms

    conferir('o Gratuito nao tem SMS', has_sms('free'), False)
    conferir('o Basico tem', has_sms('basic'), True)
    # O corte mora em `resolve_api_key` e vira `SmsChannelDisabled`, que
    # `_send` ja trata sem derrubar a entrega de e-mail.
    sms_py = Path(dj_settings.BASE_DIR, 'communications', 'smsdev.py').read_text(encoding='utf-8')
    conferir('e a recusa por plano e SmsChannelDisabled',
             'has_sms' in sms_py and 'SmsChannelDisabled' in sms_py, True)
    servicos = Path(dj_settings.BASE_DIR, 'communications', 'services.py').read_text(encoding='utf-8')
    conferir('que `_send` trata sem derrubar o outro canal',
             'except SmsChannelDisabled' in servicos, True)

finally:
    from communications.models import DeliveryAttempt, DocumentAccessToken

    # `DeliveryAttempt.delivery` e PROTECT: a tentativa e o registro de que
    # algo foi mandado, e nao se apaga por tras da entrega.
    DeliveryAttempt.objects.filter(
        delivery__document_id__in=criados['documentos'],
    ).delete()
    Delivery.objects.filter(tenant=tenant, document_id__in=criados['documentos']).delete()
    DocumentAccessToken.objects.filter(document_id__in=criados['documentos']).delete()
    MedicalDocument.objects.filter(id__in=criados['documentos']).delete()
    PatientContact.objects.filter(id__in=criados['contatos']).delete()
    n = Patient.objects.filter(id__in=criados['pacientes']).delete()[0]
    print(f'{CHR}  limpeza: {n} objeto(s) removidos')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print(CHR + 'OK: a mensagem cabe no SMS, o e-mail sai mesmo com o SMS quebrado,')
print('    a entrega sai pelo worker e o primeiro envio e automatico.')
