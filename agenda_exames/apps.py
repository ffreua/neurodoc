from django.apps import AppConfig


class AgendaExamesConfig(AppConfig):
    name = 'agenda_exames'
    verbose_name = 'Agendas de exame'

    def ready(self):
        from events.dispatcher import register_handler

        from .lembretes import TOPICO_LEMBRETE, tratar_lembrete

        register_handler(TOPICO_LEMBRETE, 'agenda_exames.lembrete', tratar_lembrete)
