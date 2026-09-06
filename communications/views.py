from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from documents.models import AttachmentScanStatus

from . import access
from .email import send_email
from .smsdev import SmsChannelDisabled, send_sms

SESSION_VERIFIED_PREFIX = 'doc_access_verified_'


def _resolve_or_404(request, raw_token):
    return access.resolve_token(raw_token)


class DocumentAccessLandingView(View):
    """The public link a patient/contact receives never opens the document
    directly -- it always lands here first. Only a session that already
    passed OTP verification for this exact token gets the bytes.
    """

    def get(self, request, raw_token):
        token = _resolve_or_404(request, raw_token)
        if token is None:
            return render(request, 'communications/access_invalid.html', status=404)
        if request.session.get(f'{SESSION_VERIFIED_PREFIX}{token.id}'):
            return self._serve(token)
        return render(request, 'communications/access_otp_request.html', {'raw_token': raw_token})

    def _serve(self, token):
        attachment = token.document.signed_pdf_attachment
        if attachment is None or attachment.scan_status != AttachmentScanStatus.AVAILABLE:
            return HttpResponse(status=404)
        with open(attachment.storage_key, 'rb') as fh:
            content = fh.read()
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{attachment.original_name}"'
        response['Cache-Control'] = 'private, no-store'
        return response


class DocumentAccessRequestOtpView(View):
    def post(self, request, raw_token):
        token = _resolve_or_404(request, raw_token)
        if token is None:
            return render(request, 'communications/access_invalid.html', status=404)
        raw_otp = access.request_otp(token)
        message = f'Seu codigo de acesso NeuroDoc: {raw_otp} (valido por 10 minutos).'
        contact = token.contact
        if contact.email_enabled and contact.verified_email_at and contact.email:
            send_email(contact.email, 'Código de acesso — NeuroDoc', message)
        elif contact.sms_enabled and contact.verified_phone_at and contact.phone:
            try:
                send_sms(contact.phone, message, refer=f'otp-{token.id}'[:100])
            except SmsChannelDisabled:
                pass
        return render(request, 'communications/access_otp_verify.html', {'raw_token': raw_token})


class DocumentAccessVerifyOtpView(View):
    def post(self, request, raw_token):
        token = _resolve_or_404(request, raw_token)
        if token is None:
            return render(request, 'communications/access_invalid.html', status=404)
        try:
            access.verify_otp(token, request.POST.get('otp', ''))
        except (access.OtpExpired, access.OtpAttemptsExceeded, access.OtpIncorrect) as exc:
            return render(
                request, 'communications/access_otp_verify.html',
                {'raw_token': raw_token, 'error': str(exc)}, status=403,
            )
        request.session[f'{SESSION_VERIFIED_PREFIX}{token.id}'] = True
        return redirect('communications:document-access', raw_token=raw_token)
