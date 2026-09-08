import hashlib
import json

from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from documents.storage import QuotaExceeded, receive_upload
from documents.tasks import scan_attachment
from documents.validators import UploadRejected
from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.models import Tenant

from . import capture
from .models import CaptureDevice, CaptureSession, CaptureUploadRecord


class TenantScopedView(CapabilityRequiredView):
    """Captura por celular: parear aparelho e abrir sessão de digitalização.

    O que entra por aqui vira anexo do paciente, então a capacidade é a do
    cadastro — a mesma de quem anexa pela tela. O que o anexo digitalizado
    revela depois continua decidido pela classificação dele, em
    `documents._attachment_or_404`.
    """

    required_capability = Capability.PATIENT_ADMIN


class DevicePairingStartView(TenantScopedView):
    def post(self, request):
        from tenancy.models import Membership

        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        device, raw_code = capture.initiate_pairing(
            Tenant.objects.get(id=request.access_context.tenant_id), request.POST.get('name', 'Scanner'), membership,
        )
        return render(request, 'integrations/capture/pairing_code.html', {'device': device, 'code': raw_code})


class DeviceListView(TenantScopedView):
    def get(self, request):
        from tenancy.selectors import scope_to_tenant

        devices = scope_to_tenant(CaptureDevice.objects.all(), request.access_context)
        return render(request, 'integrations/capture/devices.html', {'devices': devices})


class DeviceRevokeView(TenantScopedView):
    def post(self, request, device_id):
        from tenancy.selectors import scope_to_tenant

        device = get_object_or_404(scope_to_tenant(CaptureDevice.objects.all(), request.access_context), id=device_id)
        capture.revoke_device(device, request.user.id)
        return redirect('integrations:capture-devices')


class SessionOpenView(TenantScopedView):
    """Requires selecting the patient (and optionally the encounter)
    explicitly, in the clinic's own authenticated screen -- never
    something the capture device itself can choose.
    """

    def post(self, request, device_id):
        from clinical.models import Encounter
        from patients.models import Patient
        from tenancy.models import Membership
        from tenancy.selectors import scope_to_tenant

        device = get_object_or_404(scope_to_tenant(CaptureDevice.objects.all(), request.access_context), id=device_id)
        patient = get_object_or_404(
            scope_to_tenant(Patient.objects.all(), request.access_context), id=request.POST.get('patient_id'),
        )
        encounter = None
        if request.POST.get('encounter_id'):
            encounter = get_object_or_404(
                scope_to_tenant(Encounter.objects.all(), request.access_context), id=request.POST['encounter_id'],
            )
        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        session, raw_token = capture.open_session(device, patient, membership, encounter=encounter)
        return render(request, 'integrations/capture/session_started.html', {'session': session, 'token': raw_token})


class BatchUploadView(View):
    """Authenticated by the session-scoped token in the URL, not by Django
    session/cookies -- this is the endpoint the capture agent (running on
    the scanning workstation, not in a browser) calls directly over HTTPS.
    """

    def post(self, request, session_token):
        session = capture.resolve_session(session_token)
        if session is None:
            return HttpResponseForbidden('Invalid or expired capture session')

        uploaded = request.FILES.get('page')
        if uploaded is None:
            return HttpResponse(status=400, content=b'Missing file field "page"')
        try:
            page_number = int(request.POST.get('page_number', '0'))
        except ValueError:
            return HttpResponse(status=400, content=b'Invalid page_number')

        content = uploaded.read()
        sha256 = hashlib.sha256(content).hexdigest()
        if CaptureUploadRecord.objects.filter(session=session, sha256=sha256).exists():
            # Same bytes already received in this session -- never attach
            # again silently; the operator sees this as a rejection, not a
            # second copy.
            return HttpResponse(status=409, content=b'Duplicate page for this session')

        try:
            attachment = receive_upload(
                context=None, tenant=session.tenant, patient=session.patient, uploaded_by=session.opened_by.user,
                content=content, original_name=uploaded.name, classification='clinical', encounter=session.encounter,
            )
        except (UploadRejected, QuotaExceeded) as exc:
            return HttpResponse(status=422, content=str(exc).encode())

        CaptureUploadRecord.objects.create(
            tenant=session.tenant, session=session, sha256=sha256, page_number=page_number, attachment=attachment,
        )
        session.page_count += 1
        session.save(update_fields=['page_count'])
        scan_attachment.delay(str(attachment.id))
        return JsonResponse({
            'status': 'received', 'page_number': page_number, 'attachment_id': str(attachment.id),
            'session_page_count': session.page_count,
        })


class SessionStatusView(View):
    """Polled by the local capture UI (S13-T10) to show the operator which
    patient/batch is active and how many pages arrived -- token-scoped,
    same as the upload endpoint, never a Django-session view.
    """

    def get(self, request, session_token):
        session = capture.resolve_session(session_token)
        if session is None:
            raise Http404
        return JsonResponse({
            'patient_name': session.patient.full_name, 'page_count': session.page_count,
            'status': session.status, 'expires_at': session.expires_at.isoformat(),
        })
