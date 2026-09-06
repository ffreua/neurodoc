from documents.models import MedicalDocument

from .services import deliver_document


def handle_document_issued(event):
    document = MedicalDocument.objects.filter(id=event.payload_minimal['medical_document_id']).first()
    if document is None:
        return
    deliver_document(document)
