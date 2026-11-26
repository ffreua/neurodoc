from ..document_kinds import TITLE
from ..models import MedicalDocumentKind
from . import exam_request, lme, prescription, referral, report, request, surgery_request

_RENDERERS = {
    MedicalDocumentKind.PRESCRIPTION: prescription.render,
    MedicalDocumentKind.REPORT: report.render,
    MedicalDocumentKind.REQUEST: request.render,
    MedicalDocumentKind.REFERRAL: referral.render,
    MedicalDocumentKind.EXAM_REQUEST: exam_request.render,
    MedicalDocumentKind.SURGERY_REQUEST: surgery_request.render,
    MedicalDocumentKind.LME: lme.render,
}


def render_medical_document_pdf(document):
    renderer = _RENDERERS[document.kind]
    return renderer(document)


__all__ = ['render_medical_document_pdf', 'TITLE']
