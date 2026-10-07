from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    name = 'communications'

    def ready(self):
        from events.dispatcher import register_handler
        from scheduling.events import CANCELLED_TOPIC, RESCHEDULED_TOPIC, RESERVED_TOPIC

        from .handlers import (
            handle_appointment_booked, handle_appointment_cancelled,
            handle_appointment_rescheduled, handle_document_issued,
        )

        register_handler('documents.document_issued', 'communications.document_issued', handle_document_issued)

        # Aviso ao paciente quando o horario dele muda de estado. Tres
        # topicos, tres consumidores: o nome do consumidor e o que separa
        # este do CRM, que ja consome `appointment_reserved` -- o
        # dispatcher aceita varios no mesmo topico, e foi essa capacidade
        # que permitiu avisar o paciente sem inventar um evento novo para
        # um fato que ja tinha o seu.
        register_handler(
            RESERVED_TOPIC, 'communications.appointment_booked', handle_appointment_booked,
        )
        register_handler(
            RESCHEDULED_TOPIC, 'communications.appointment_rescheduled',
            handle_appointment_rescheduled,
        )
        register_handler(
            CANCELLED_TOPIC, 'communications.appointment_cancelled',
            handle_appointment_cancelled,
        )
