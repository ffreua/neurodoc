from ..document_kinds import TITLE
from ..models import MedicalDocumentKind
from . import prescription, referral, report, request

_RENDERERS = {
    MedicalDocumentKind.PRESCRIPTION: prescription.render,
    MedicalDocumentKind.REPORT: report.render,
    MedicalDocumentKind.REQUEST: request.render,
    MedicalDocumentKind.REFERRAL: referral.render,
}


def render_medical_document_pdf(document):
    renderer = _RENDERERS[document.kind]
    return renderer(document)


__all__ = ['render_medical_document_pdf', 'TITLE']
