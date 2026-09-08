"""O que o paciente abre quando recebe o link do documento.

Público, sem conta e sem sessão prévia. É a única parte do sistema que uma
pessoa de fora alcança com dados clínicos do outro lado — e por isso cada
passo aqui é conservador: o link sozinho não abre nada, a conferência tem
limite de tentativas, e o PDF sai com cabeçalhos que impedem cache
compartilhado.
"""

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from audit.services import record_audit_event
from documents.models import AttachmentScanStatus

from . import access

SESSION_VERIFIED_PREFIX = 'doc_access_verified_'


def _document_summary(token):
    """O que a tela mostra antes de a pessoa provar quem é.

    Tipo do documento e clínica, e nada mais. Nome do paciente não entra:
    um link que caiu em mãos erradas não pode confirmar de quem ele é antes
    de a pessoa acertar a resposta.
    """
    document = token.document
    return {
        'kind': document.get_kind_display(),
        'clinic': document.tenant.trade_name or document.tenant.legal_name,
        'challenge': access.challenge_kind(token),
        'attempts_left': access.attempts_left(token),
    }


class DocumentAccessLandingView(View):
    """O link cai aqui, nunca no arquivo.

    Só uma sessão que já acertou a conferência **para este token** recebe
    os bytes do PDF.
    """

    def get(self, request, raw_token):
        token = access.resolve_token(raw_token)
        if token is None:
            return render(request, 'communications/access_invalid.html', status=404)
        if request.session.get(f'{SESSION_VERIFIED_PREFIX}{token.id}'):
            return render(request, 'communications/access_document.html', {
                'raw_token': raw_token,
                'document': token.document,
                'clinic': token.document.tenant.trade_name or token.document.tenant.legal_name,
            })
        return render(request, 'communications/access_challenge.html', {
            'raw_token': raw_token, **_document_summary(token),
        })

    def post(self, request, raw_token):
        token = access.resolve_token(raw_token)
        if token is None:
            return render(request, 'communications/access_invalid.html', status=404)
        try:
            access.verify_identity(token, request.POST.get('answer', ''))
        except access.AccessLocked as exc:
            record_audit_event(
                None, token.tenant_id, 'communications.document_access_locked',
                object_type='medical_document', object_id=token.document_id, outcome='denied',
            )
            return render(request, 'communications/access_challenge.html', {
                'raw_token': raw_token, 'error': str(exc), 'locked': True,
                **_document_summary(token),
            }, status=429)
        except access.AccessDenied as exc:
            record_audit_event(
                None, token.tenant_id, 'communications.document_access_denied',
                object_type='medical_document', object_id=token.document_id, outcome='denied',
            )
            return render(request, 'communications/access_challenge.html', {
                'raw_token': raw_token, 'error': str(exc), **_document_summary(token),
            }, status=403)

        request.session[f'{SESSION_VERIFIED_PREFIX}{token.id}'] = True
        record_audit_event(
            None, token.tenant_id, 'communications.document_accessed',
            object_type='medical_document', object_id=token.document_id, outcome='success',
        )
        return redirect('communications:document-access', raw_token=raw_token)


class DocumentAccessFileView(View):
    """Serve o PDF a quem já passou pela conferência.

    Rota separada da tela para o `<iframe>` de leitura, o botão de imprimir
    e o de baixar apontarem para o mesmo arquivo sem repetir a verificação
    em três lugares.
    """

    def get(self, request, raw_token):
        token = access.resolve_token(raw_token)
        if token is None:
            return HttpResponse(status=404)
        if not request.session.get(f'{SESSION_VERIFIED_PREFIX}{token.id}'):
            # 404 e não 403: quem chegou nesta URL sem passar pela
            # conferência não deve nem confirmar que o arquivo existe.
            return HttpResponse(status=404)

        attachment = token.document.signed_pdf_attachment
        if attachment is None or attachment.scan_status != AttachmentScanStatus.AVAILABLE:
            return HttpResponse(status=404)
        with open(attachment.storage_key, 'rb') as fh:
            content = fh.read()

        baixar = request.GET.get('baixar') == '1'
        disposition = 'attachment' if baixar else 'inline'
        nome = f'{token.document.document_number or "documento"}.pdf'
        response = HttpResponse(content, content_type='application/pdf')
        response['Content-Disposition'] = f'{disposition}; filename="{nome}"'
        # `no-store` e `private`: documento clínico não pode ficar em cache
        # de proxy nem no disco de um navegador compartilhado — lan house,
        # computador de trabalho, tablet da recepção.
        response['Cache-Control'] = 'private, no-store, max-age=0'
        response['X-Content-Type-Options'] = 'nosniff'
        record_audit_event(
            None, token.tenant_id,
            'communications.document_downloaded' if baixar else 'communications.document_viewed',
            object_type='medical_document', object_id=token.document_id, outcome='success',
        )
        return response
