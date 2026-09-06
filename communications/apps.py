from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    name = 'communications'

    def ready(self):
        from events.dispatcher import register_handler

        from .handlers import handle_document_issued

        register_handler('documents.document_issued', 'communications.document_issued', handle_document_issued)
