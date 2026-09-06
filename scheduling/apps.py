from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    name = 'scheduling'

    def ready(self):
        from events.dispatcher import register_handler

        from .events import REMINDER_TOPIC_PREFIX
        from .handlers import handle_appointment_reminder

        register_handler(REMINDER_TOPIC_PREFIX, 'scheduling.appointment_reminder', handle_appointment_reminder)
