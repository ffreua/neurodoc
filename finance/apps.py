from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = 'finance'

    def ready(self):
        from events.dispatcher import register_handler

        from .handlers import handle_encounter_finalized

        register_handler('clinical.encounter_finalized', 'finance.encounter_finalized', handle_encounter_finalized)
