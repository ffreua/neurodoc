"""A entrega que falha no transporte é tentada de novo (auditoria de 2026-11-11).

O SMTP fora por um minuto, ou o SMSDEV respondendo 500, devolvia a entrega
a "Na fila" e `_send` retornava calado: o consumidor terminava sem erro, o
despachante dava o evento por concluído, e nada voltava a olhar a entrega.
O paciente ficava sem o link ou sem o lembrete, e a tela dizia "Na fila".

O roteiro roda o consumidor do documento emitido como o despachante roda,
com o e-mail falhando e o SMS funcionando, e confere: o consumidor levanta
para ser tentado de novo; a repetição manda **só** o que ficou na fila (o
SMS não sai duas vezes); e, na última tentativa, a entrega vira "Falhou"
em vez de ficar "Na fila" para sempre.

Tudo dentro de transação desfeita; o provedor é simulado.

    docker compose exec -T app python manage.py shell < checks/check_entrega_tenta_de_novo.py
"""
import secrets
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from communications import handlers, services
from communications.email import EmailSendFailed
from communications.models import Delivery, DeliveryChannel, DeliveryStatus
from documents.models import MedicalDocument
from events.dispatcher import MAX_ATTEMPTS
from patients.models import Patient, PatientContact, RegistrationStage
from tenancy.models import Membership, Tenant

falhas = []
SUFIXO = secrets.token_hex(3)


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Provedor:
    def __init__(self, email_falha):
        self.email_falha = email_falha
        self.enviados = []

    def sms(self, phone, message, **_):
        self.enviados.append('sms')
        return {'id': f'roteiro-{len(self.enviados)}'}

    def email(self, to, subject, message, **_):
        if self.email_falha:
            raise EmailSendFailed('SMTP fora do ar (simulado)')
        self.enviados.append('email')


class Remendo:
    def __init__(self, *trocas):
        self.trocas = trocas

    def __enter__(self):
        self.originais = [(alvo, nome, getattr(alvo, nome)) for alvo, nome, _ in self.trocas]
        for alvo, nome, novo in self.trocas:
            setattr(alvo, nome, novo)

    def __exit__(self, *exc):
        for alvo, nome, original in self.originais:
            setattr(alvo, nome, original)


def consumir(documento, provedor, tentativa):
    """O consumidor, como o despachante o chama. Devolve se levantou."""
    evento = SimpleNamespace(payload_minimal={'medical_document_id': str(documento.id)}, attempts=tentativa)
    with Remendo((services, 'send_sms', provedor.sms), (services, 'send_email', provedor.email)):
        try:
            handlers.handle_document_issued(evento)
        except services.EntregaAdiada:
            return True
    return False


def situacao(documento, canal):
    return Delivery.objects.get(document=documento, channel=canal).status


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(tenant=tenant, user__email='doctor-a@demo.neurodoc.local').first()

try:
    with transaction.atomic():
        agora = timezone.now()
        paciente = Patient.objects.create(
            tenant=tenant, full_name=f'PACIENTE ENTREGA DE NOVO {SUFIXO}',
            registration_stage=RegistrationStage.COMPLETE,
        )
        PatientContact.objects.create(
            tenant=tenant, patient=paciente, name=paciente.full_name,
            email=f'denovo.{SUFIXO}@example.invalid', phone='11977775555',
            verified_email_at=agora, verified_phone_at=agora,
            authorized_for_documents=True, email_enabled=True, sms_enabled=True,
        )

        def documento_novo():
            return MedicalDocument.objects.create(
                tenant=tenant, patient=paciente, physician=medico, kind='prescription', status='issued',
            )

        print('=== 1. O e-mail falha no transporte: o consumidor levanta ===')
        doc = documento_novo()
        p = Provedor(email_falha=True)
        levantou = consumir(doc, p, tentativa=1)
        conferir('o consumidor levanta para o despachante tentar de novo', levantou)
        conferir('o SMS saiu', p.enviados.count('sms') == 1, p.enviados)
        conferir('o e-mail ficou na fila', situacao(doc, DeliveryChannel.EMAIL) == DeliveryStatus.PENDING,
                 situacao(doc, DeliveryChannel.EMAIL))

        print('=== 2. A repetição manda só o que ficou na fila ===')
        p2 = Provedor(email_falha=False)
        levantou = consumir(doc, p2, tentativa=2)
        conferir('com o SMTP de volta, o consumidor termina', not levantou)
        conferir('o e-mail sai na repetição', p2.enviados.count('email') == 1, p2.enviados)
        conferir('e o SMS não sai de novo', p2.enviados.count('sms') == 0, p2.enviados)
        conferir('a entrega de e-mail foi aceita',
                 situacao(doc, DeliveryChannel.EMAIL) == DeliveryStatus.ACCEPTED,
                 situacao(doc, DeliveryChannel.EMAIL))

        print('=== 3. Na última tentativa, "Falhou" e não "Na fila" ===')
        doc3 = documento_novo()
        levantou = consumir(doc3, Provedor(email_falha=True), tentativa=MAX_ATTEMPTS)
        conferir('na última tentativa o consumidor não levanta mais', not levantou)
        conferir('a entrega aparece como falhou, para alguém reenviar',
                 situacao(doc3, DeliveryChannel.EMAIL) == DeliveryStatus.FAILED,
                 situacao(doc3, DeliveryChannel.EMAIL))

        print('=== 4. Tudo entregue: nada levanta ===')
        doc4 = documento_novo()
        conferir('sem falha, o consumidor termina como antes',
                 not consumir(doc4, Provedor(email_falha=False), tentativa=1))

        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('OK: a falha de transporte volta a ser tentada, sem repetir o que já saiu.')
