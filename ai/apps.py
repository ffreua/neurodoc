from django.apps import AppConfig


class AiConfig(AppConfig):
    name = 'ai'

    def ready(self):
        from events.dispatcher import register_handler

        from .handlers import handle_encounter_finalized

        register_handler('clinical.encounter_finalized', 'ai.encounter_finalized', handle_encounter_finalized)
