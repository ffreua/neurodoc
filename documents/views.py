from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from audit.services import record_audit_event
from patients.models import Patient
from tenancy.selectors import scope_to_tenant

from .forms import AttachmentUploadForm
from .models import Attachment, AttachmentScanStatus
from .preview import PreviewUnavailable, render_preview_png
from .retention import soft_delete_attachment
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
