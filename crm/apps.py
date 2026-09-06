from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = 'crm'

    def ready(self):
        from events.dispatcher import register_handler
        from scheduling.events import RESERVED_TOPIC

        from .handlers import handle_appointment_reserved

        register_handler(RESERVED_TOPIC, 'crm.appointment_reserved', handle_appointment_reserved)
