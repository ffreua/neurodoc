"""Página pública de verificação de documento — o destino do QR.

Quem abre esta página está com um papel na mão: o balconista da farmácia, a
recepção do laboratório, o setor de perícia do convênio. A pergunta é uma
só — **este documento saiu mesmo daquele consultório?** — e a resposta não
exige, nem pode incluir, o conteúdo clínico.

Por isso o que sai daqui é: que tipo de documento é, quem o assinou, quando,
sob que número, e o hash do arquivo assinado. Nome do paciente sai
mascarado, e prescrição, hipótese e laudo não saem de forma alguma. Quem
precisa do conteúdo já o tem em mãos, impresso.

A verificação criptográfica da assinatura ICP-Brasil continua sendo feita no
validador do ITI ou em leitor de PDF compatível; esta página confirma a
existência e a proveniência do documento no sistema que o emitiu.
"""

from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from .models import MedicalDocument, MedicalDocumentStatus
from base.net import client_ip

#: Tentativas por janela, por IP. A página é pública e o código tem 64 bits;
#: o limite existe para que nem valha a pena tentar, e para que a tentativa
#: apareça no log em vez de passar despercebida.
LOOKUP_MAX_ATTEMPTS = 20
LOOKUP_WINDOW_SECONDS = 900


def mask_patient_name(full_name):
    """Primeiro nome inteiro, o resto só a inicial.

    O suficiente para conferir contra o papel — "é a receita da Maria?" — e
    insuficiente para identificar alguém a partir de um código achado por
    acaso.
    """
    parts = [p for p in (full_name or '').split() if p]
    if not parts:
        return ''
    if len(parts) == 1:
        return f'{parts[0][0]}***'
    return f'{parts[0]} {parts[-1][0]}***'


def _too_many_attempts(request):
    """Limite por IP, na cache que a instalação já usa.

    Falha aberto de propósito: se o Redis estiver fora, a farmácia continua
    conseguindo conferir a receita. O risco de deixar passar tentativa de
    adivinhação durante uma indisponibilidade é menor do que o de recusar a
    verificação de um documento legítimo.
    """
    from django.core.cache import cache

    ip = client_ip(request)
    key = f'docverify:{ip}'
    try:
        count = cache.get_or_set(key, 0, LOOKUP_WINDOW_SECONDS)
        count = cache.incr(key)
    except Exception:                                   # noqa: BLE001
        return False
    return count > LOOKUP_MAX_ATTEMPTS


def _lookup(token):
    clean = ''.join(c for c in (token or '').upper() if c.isalnum())
    if not (16 <= len(clean) <= 64):
        return None
    return (
        MedicalDocument.objects
        .select_related('patient', 'physician__user', 'tenant')
        .filter(validation_token=clean)
        .first()
    )


class DocumentVerificationView(View):
    """Aberta, sem sessão. É o que o QR impresso alcança."""

    template_name = 'documents/verify.html'

    def get(self, request, token=''):
        return self._respond(request, token or request.GET.get('codigo', ''))

    def post(self, request, token=''):
        return self._respond(request, request.POST.get('codigo', ''))

    def _respond(self, request, token):
        from audit.services import record_audit_event

        context = {'submitted': bool(token), 'codigo': token, 'document': None, 'error': ''}

        if token and _too_many_attempts(request):
            context['error'] = (
                'Muitas consultas a partir deste endereço. Aguarde alguns minutos '
                'e tente novamente.'
            )
            return render(request, self.template_name, context, status=429)

        document = _lookup(token) if token else None
        if token and document is None:
            context['error'] = (
                'Nenhum documento com este código. Confira a digitação, ou leia o '
                'QR code impresso no documento.'
            )
            return render(request, self.template_name, context, status=404)

        if document is not None:
            profile = getattr(document.physician.user, 'physician_profile', None)
            issued = document.status == MedicalDocumentStatus.ISSUED
            context['document'] = {
                'issued': issued,
                'kind': document.get_kind_display(),
                'number': document.document_number,
                'version': document.version,
                'patient': mask_patient_name(document.patient.full_name),
                'physician': profile.professional_name if profile else '',
                'crm': f'{profile.crm_number}/{profile.crm_state}' if profile else '',
                'clinic': document.tenant.trade_name or document.tenant.legal_name,
                'issued_at': document.issued_at,
                'sha256': (document.signature_metadata or {}).get('content_sha256', ''),
                'superseded_by': document.replaced_by.filter(
                    status=MedicalDocumentStatus.ISSUED,
                ).first(),
            }
            # Consulta de documento é evento de auditoria: é a forma de
            # perceber depois que alguém varreu códigos. Sem o código no
            # log — ele é a credencial de acesso a esta página.
            record_audit_event(
                None, document.tenant_id, 'documents.verification_page_viewed',
                object_type='medical_document', object_id=document.id,
                outcome='success' if issued else 'denied',
                integrity_metadata={'issued': issued},
            )

        context['now'] = timezone.now()
        return render(request, self.template_name, context)
