import logging
from datetime import timedelta

from django.utils import timezone

from documents.models import MedicalDocument

from .services import deliver_document

logger = logging.getLogger(__name__)


def handle_document_issued(event):
    document = MedicalDocument.objects.filter(id=event.payload_minimal['medical_document_id']).first()
    if document is None:
        return
    deliver_document(document)


#: Idade máxima de um evento para ele ainda virar aviso ao paciente.
#:
#: **Existe por um acidente real, em 2026-10-07.** `appointment_reserved`
#: era emitido desde sempre e **ninguém o consumia** — e o dispatcher
#: deixa evento sem consumidor pendente de propósito, para que "um deploy
#: futuro possa registrar" (é o que o comentário dele diz). Isso está
#: certo para integração de **dados**: um CRM que chega depois quer o
#: histórico.
#:
#: Está errado para **mensagem a uma pessoa**. Quando o consumidor do
#: aviso entrou no ar, à 01h12, ele encontrou 48 eventos pendentes e
#: processou todos: dez e-mails saíram à 01h15 dizendo "sua consulta está
#: marcada" — para consultas que já tinham acontecido, e para duas que
#: haviam sido canceladas.
#:
#: Seis horas é generoso de propósito: cobre o worker fora do ar por uma
#: tarde inteira, e ainda assim nenhum evento de dias atrás passa.
JANELA_DO_AVISO = timedelta(hours=6)


def _aviso(event, motivo):
    """Consumidor dos eventos de horário: avisa o paciente por e-mail.

    Mora em `communications` e não em `scheduling` porque quem entrega é
    este app — e porque o CRM já consome `appointment_reserved` por conta
    própria. O dispatcher aceita vários consumidores no mesmo tópico, e é
    isso que permite o aviso ao paciente entrar sem um evento novo para o
    fato que já tinha um.

    **Evento velho não vira aviso.** Ver `JANELA_DO_AVISO`: um consumidor
    novo encontra toda a história pendente do tópico, e avisar sobre ela
    é escrever para pacientes sobre consultas que já passaram.
    """
    from scheduling.models import Appointment

    from .services import deliver_appointment_notice

    # `created_at`, e nunca `available_at`. Aquele é quando o fato
    # aconteceu; este é **quando tentar de novo**, e o despachante o
    # empurra para a frente a cada espera sem consumidor e a cada recuo.
    # Medida por ele, a janela via todo evento como recém-nascido: o de
    # dez dias atrás, empurrado há dois minutos, passava -- que é
    # exatamente o replay que ela existe para barrar (auditoria de
    # 2026-10-09, A6).
    idade = timezone.now() - event.created_at
    if idade > JANELA_DO_AVISO:
        logger.info(
            'Aviso de horário descartado por evento antigo',
            extra={'topic': event.topic, 'idade_horas': round(idade.total_seconds() / 3600, 1)},
        )
        return

    appointment = Appointment.objects.filter(
        id=event.payload_minimal.get('appointment_id'),
    ).select_related('tenant', 'patient', 'physician_membership__user').first()
    if appointment is None:
        return
    deliver_appointment_notice(appointment, motivo, event.event_version)


def handle_appointment_booked(event):
    _aviso(event, 'booked')


def handle_appointment_rescheduled(event):
    _aviso(event, 'rescheduled')


def handle_appointment_cancelled(event):
    _aviso(event, 'cancelled')
