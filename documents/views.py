from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.services import record_audit_event
from patients.models import Patient
from tenancy.selectors import scope_to_tenant

from . import credentials as credentials_services
from . import document_kinds
from . import issuance
from . import signing_sessions
from .forms import AttachmentUploadForm, CredentialUploadForm, MedicalDocumentForm, SigningSessionStartForm
from .models import Attachment, AttachmentScanStatus, MedicalDocument, SigningCredential
from .preview import PreviewUnavailable, render_preview_png
from .retention import soft_delete_attachment
from .signing import InvalidPfxPassword
from .storage import QuotaExceeded, receive_upload
from .tasks import scan_attachment
from .validators import UploadRejected


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _patient_or_404(request, patient_id):
    return get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)


def _attachment_or_404(request, attachment_id):
    attachment = scope_to_tenant(Attachment.objects.all(), request.access_context).filter(
        id=attachment_id, deleted_at=None,
    ).first()
    if attachment is None:
        raise Http404
    return attachment


class AttachmentListView(TenantScopedView):
    def get(self, request, patient_id):
        patient = _patient_or_404(request, patient_id)
        attachments = patient.attachments.filter(deleted_at=None).order_by('-created_at')
        return render(request, 'documents/list.html', {
            'patient': patient, 'attachments': attachments, 'form': AttachmentUploadForm(),
        })

    def post(self, request, patient_id):
        patient = _patient_or_404(request, patient_id)
        form = AttachmentUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            attachments = patient.attachments.filter(deleted_at=None).order_by('-created_at')
            return render(request, 'documents/list.html', {'patient': patient, 'attachments': attachments, 'form': form})
        uploaded = request.FILES['file']
        from tenancy.models import Tenant
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            attachment = receive_upload(
                request.access_context, tenant, patient, request.user, uploaded.read(), uploaded.name,
                form.cleaned_data['classification'], document_date=form.cleaned_data.get('document_date'),
            )
        except (UploadRejected, QuotaExceeded) as exc:
            form.add_error('file', str(exc))
            attachments = patient.attachments.filter(deleted_at=None).order_by('-created_at')
            return render(request, 'documents/list.html', {'patient': patient, 'attachments': attachments, 'form': form})
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.attachment_uploaded',
            object_type='attachment', object_id=attachment.id, outcome='success',
        )
        scan_attachment.delay(str(attachment.id))
        return redirect('documents:list', patient_id=patient.id)


class AttachmentDownloadView(TenantScopedView):
    def get(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        if attachment.scan_status != AttachmentScanStatus.AVAILABLE:
            record_audit_event(
                request.user, request.access_context.tenant_id, 'documents.attachment_download_denied',
                object_type='attachment', object_id=attachment.id, outcome='denied',
            )
            raise Http404
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.attachment_downloaded',
            object_type='attachment', object_id=attachment.id, outcome='success',
        )
        response = HttpResponse(open(attachment.storage_key, 'rb').read(), content_type=attachment.mime)
        response['Content-Disposition'] = f'attachment; filename="{attachment.original_name}"'
        response['Cache-Control'] = 'private, no-store'
        return response


class AttachmentPreviewView(TenantScopedView):
    def get(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        try:
            png_bytes = render_preview_png(attachment)
        except PreviewUnavailable:
            raise Http404
        response = HttpResponse(png_bytes, content_type='image/png')
        response['Cache-Control'] = 'private, no-store'
        return response


class AttachmentDeleteView(TenantScopedView):
    def post(self, request, attachment_id):
        attachment = _attachment_or_404(request, attachment_id)
        soft_delete_attachment(attachment, request.user.id, request.POST.get('reason', ''))
        return redirect('documents:list', patient_id=attachment.patient_id)


def _encounter_or_404(request, encounter_id):
    from clinical.models import Encounter

    encounter = scope_to_tenant(Encounter.objects.all(), request.access_context).filter(id=encounter_id).first()
    if encounter is None:
        raise Http404
    return encounter


def _medical_document_or_404(request, document_id):
    document = scope_to_tenant(MedicalDocument.objects.all(), request.access_context).filter(id=document_id).first()
    if document is None:
        raise Http404
    return document


def _own_doctor_membership_or_403(request):
    """Every signing-adjacent action acts strictly as *this* logged-in
    user's own membership -- there is no "act on behalf of" path, which is
    exactly what keeps a secretary/manager/AI session from ever touching a
    physician's signing session (S07-T08).
    """
    from tenancy.models import Membership

    if not request.access_context.has_role('doctor'):
        return None
    return Membership.objects.filter(id=request.access_context.membership_id).select_related('user').first()


class MedicalDocumentListView(TenantScopedView):
    def get(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        documents = encounter.medical_documents.order_by('-created_at')
        return render(request, 'documents/medical_list.html', {'encounter': encounter, 'documents': documents})


class MedicalDocumentCreateView(TenantScopedView):
    def get(self, request, encounter_id):
        _encounter_or_404(request, encounter_id)
        return render(request, 'documents/medical_form.html', {'form': MedicalDocumentForm()})

    def post(self, request, encounter_id):
        encounter = _encounter_or_404(request, encounter_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Only a doctor membership may author a medical document.')
        form = MedicalDocumentForm(request.POST)
        if not form.is_valid():
            return render(request, 'documents/medical_form.html', {'form': form})
        kind = form.cleaned_data['kind']
        content_fields = {field: form.cleaned_data[field] for field in document_kinds.all_fields(kind)}
        from tenancy.models import Tenant

        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            document = issuance.create_draft(
                tenant, encounter.patient, encounter, physician_membership, request.user.id, kind, content_fields,
            )
        except (ValueError, issuance.MissingPhysicianProfile) as exc:
            form.add_error(None, str(exc))
            return render(request, 'documents/medical_form.html', {'form': form})
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentDetailView(TenantScopedView):
    def get(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        is_own_document = physician_membership is not None and physician_membership.id == document.physician_id
        active_session = None
        credentials = []
        if is_own_document:
            active_session = signing_sessions.get_active_session(request, physician_membership)
            credentials = SigningCredential.objects.filter(physician=physician_membership).order_by('-created_at')
        return render(request, 'documents/medical_detail.html', {
            'document': document, 'is_own_document': is_own_document,
            'active_session': active_session, 'credentials': credentials,
            'session_form': SigningSessionStartForm(), 'credential_form': CredentialUploadForm(),
        })


class MedicalDocumentReviewView(TenantScopedView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != document.physician_id:
            return HttpResponseForbidden('Only the authoring physician may review this document.')
        try:
            issuance.mark_reviewed(document, request.user.id)
        except issuance.NotReadyToSign as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentDiscardView(TenantScopedView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != document.physician_id:
            return HttpResponseForbidden('Only the authoring physician may discard this document.')
        encounter_id = document.encounter_id
        try:
            issuance.discard_document(document, request.user.id)
        except issuance.NotReadyToSign as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('documents:medical-list', encounter_id=encounter_id)


class MedicalDocumentSignView(TenantScopedView):
    def post(self, request, document_id):
        document = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Only a doctor membership may sign.')
        try:
            issuance.sign_and_issue(document, request, physician_membership)
        except (issuance.NotReadyToSign, issuance.SigningNotAuthorized) as exc:
            return render(request, 'documents/medical_detail.html', {
                'document': document, 'is_own_document': True, 'sign_error': str(exc),
                'active_session': signing_sessions.get_active_session(request, physician_membership),
                'credentials': SigningCredential.objects.filter(physician=physician_membership),
                'session_form': SigningSessionStartForm(), 'credential_form': CredentialUploadForm(),
            }, status=409)
        return redirect('documents:medical-detail', document_id=document.id)


class MedicalDocumentCorrectionView(TenantScopedView):
    def post(self, request, document_id):
        original = _medical_document_or_404(request, document_id)
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None or physician_membership.id != original.physician_id:
            return HttpResponseForbidden('Only the authoring physician may correct this document.')
        form = MedicalDocumentForm(request.POST)
        if not form.is_valid():
            return render(request, 'documents/medical_form.html', {'form': form})
        content_fields = {field: form.cleaned_data[field] for field in document_kinds.all_fields(original.kind)}
        new_document = issuance.create_correction(original, request.user.id, content_fields)
        return redirect('documents:medical-detail', document_id=new_document.id)


class SigningCredentialUploadView(TenantScopedView):
    def post(self, request):
        from tenancy.models import Tenant

        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Only a doctor membership may upload a signing credential.')
        from accounts import mfa

        if not mfa.mfa_verified_recently(request):
            return HttpResponseForbidden('Recent MFA verification required.')
        form = CredentialUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return HttpResponseForbidden('Invalid form.')
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)
        try:
            credentials_services.upload_credential(
                tenant, physician_membership, form.cleaned_data['pfx_file'].read(), form.cleaned_data['password'],
            )
        except (credentials_services.InvalidPfxFile, credentials_services.CredentialTitleMismatch) as exc:
            return HttpResponseForbidden(str(exc))
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingcredential_uploaded',
            object_type='signing_credential', outcome='success',
        )
        return redirect('documents:credential-list')


class SigningCredentialListView(TenantScopedView):
    def get(self, request):
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Only a doctor membership has signing credentials.')
        creds = SigningCredential.objects.filter(physician=physician_membership).order_by('-created_at')
        active_session = signing_sessions.get_active_session(request, physician_membership)
        return render(request, 'documents/credentials.html', {
            'credentials': creds, 'active_session': active_session,
            'credential_form': CredentialUploadForm(), 'session_form': SigningSessionStartForm(),
        })


class SigningCredentialRevokeView(TenantScopedView):
    def post(self, request, credential_id):
        physician_membership = _own_doctor_membership_or_403(request)
        credential = SigningCredential.objects.filter(id=credential_id, physician=physician_membership).first() \
            if physician_membership else None
        if credential is None:
            return HttpResponseForbidden('Credential not found for this physician.')
        credentials_services.revoke_credential(credential)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingcredential_revoked',
            object_type='signing_credential', object_id=credential.id, outcome='success',
        )
        return redirect('documents:credential-list')


class SigningSessionStartView(TenantScopedView):
    def post(self, request):
        physician_membership = _own_doctor_membership_or_403(request)
        if physician_membership is None:
            return HttpResponseForbidden('Only a doctor membership may start a signing session.')
        form = SigningSessionStartForm(request.POST)
        if not form.is_valid():
            return HttpResponseForbidden('Invalid form.')
        credential = SigningCredential.objects.filter(
            id=form.cleaned_data['credential_id'], physician=physician_membership,
        ).first()
        if credential is None:
            return HttpResponseForbidden('Credential not found for this physician.')
        try:
            signing_sessions.start_session(
                request, physician_membership, credential,
                form.cleaned_data['password'], int(form.cleaned_data['duration_hours']),
            )
        except (
            signing_sessions.RecentMfaRequired, signing_sessions.InvalidDuration,
            signing_sessions.CredentialNotUsable,
        ) as exc:
            return HttpResponseForbidden(str(exc))
        except InvalidPfxPassword:
            record_audit_event(
                request.user, request.access_context.tenant_id, 'documents.signingsession_start_failed',
                object_type='signing_credential', object_id=credential.id, outcome='denied',
            )
            return HttpResponseForbidden('Invalid PFX password.')
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingsession_started',
            object_type='signing_credential', object_id=credential.id, outcome='success',
        )
        return redirect('documents:credential-list')


class SigningSessionRevokeView(TenantScopedView):
    def post(self, request, session_id):
        from .models import SigningSession

        physician_membership = _own_doctor_membership_or_403(request)
        session = SigningSession.objects.filter(id=session_id, physician=physician_membership).first() \
            if physician_membership else None
        if session is None:
            return HttpResponseForbidden('Session not found for this physician.')
        signing_sessions.revoke_session(session)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'documents.signingsession_revoked',
            object_type='signing_session', object_id=session.id, outcome='success',
        )
        return redirect('documents:credential-list')
