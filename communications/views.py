"""O que o paciente abre quando recebe o link do documento.

Público, sem conta e sem sessão prévia. É a única parte do sistema que uma
pessoa de fora alcança com dados clínicos do outro lado — e por isso cada
passo aqui é conservador: o link sozinho não abre nada, a conferência tem
limite de tentativas, e o PDF sai com cabeçalhos que impedem cache
compartilhado.
"""

from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin

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

    A página fica fora do cache do navegador, como o PDF já ficava
    (auditoria de 2026-11-11): ela mostra o documento e o médico.
    """

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store, max-age=0'
        return response

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


# O PDF é lido dentro de um `<iframe>` da própria página de acesso, e o
# `X-Frame-Options: DENY` global o recusava: a moldura saía em branco para o
# paciente (auditoria externa de 2026-11-20). `SAMEORIGIN` só aqui — a tela
# de acesso continua `DENY`, e outro site continua sem poder emoldurar.
@method_decorator(xframe_options_sameorigin, name='dispatch')
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
        from documents.storage import read_bytes

        content = read_bytes(attachment)

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


class UnsubscribeView(View):
    """Descadastro em um clique, sem conta e sem senha.

    A LGPD (art. 8º, §5º) manda que revogar o consentimento seja tão fácil
    quanto dá-lo. Exigir login, ou pedir para "responder este e-mail
    escrevendo SAIR", é obstruir a revogação.

    O `GET` confirma antes de agir: cliente de e-mail que pré-carrega links
    descadastraria a pessoa sem ela ter clicado. Um botão a mais é barato;
    descadastrar alguém que não pediu é perder o consentimento que a
    clínica tinha.
    """

    template_name = 'communications/unsubscribe.html'

    def _contact(self, token):
        from patients.models import PatientContact

        if not token or len(token) < 20:
            return None
        return PatientContact.objects.filter(
            marketing_unsubscribe_token=token,
        ).select_related('tenant').first()

    def get(self, request, token):
        contact = self._contact(token)
        if contact is None:
            return render(request, self.template_name, {'invalid': True}, status=404)
        return render(request, self.template_name, {
            'token': token,
            'clinic': contact.tenant.trade_name or contact.tenant.legal_name,
            'already': contact.marketing_opt_out_at is not None,
        })

    def post(self, request, token):
        from .marketing import unsubscribe

        contact = self._contact(token)
        if contact is None:
            return render(request, self.template_name, {'invalid': True}, status=404)
        unsubscribe(contact, source='link')
        return render(request, self.template_name, {
            'token': token,
            'clinic': contact.tenant.trade_name or contact.tenant.legal_name,
            'done': True,
        })


#: Agentes que abrem o link sem ser a pessoa: o antivírus do provedor que
#: confere o endereço antes da entrega, a pré-visualização do mensageiro e
#: o robô de busca. Contá-los inflaria os cliques de toda campanha.
ROBOS = (
    'bot', 'crawl', 'spider', 'slurp', 'preview', 'facebookexternalhit', 'whatsapp',
    'proofpoint', 'mimecast', 'barracuda', 'safelinks', 'scanner', 'python-requests',
    'curl', 'wget', 'headless', 'go-http-client', 'okhttp', 'java/', 'libwww',
)

#: Janela em que o mesmo visitante clicando de novo no mesmo link conta uma
#: vez só. O IP entra só no cache, embaralhado e com prazo — nunca no banco.
JANELA_DO_MESMO_CLIQUE = 30 * 60


class CampaignClickView(View):
    """Conta o clique num link de campanha e leva ao destino.

    Sem login, sem pergunta: é o link que o paciente clicou no e-mail. O
    destino é o gravado ao enviar (vindo do HTML já limpo, só `http(s)`),
    nunca um parâmetro da requisição — senão este endereço viraria um
    redirecionador aberto com o domínio do sistema.
    """

    def _conta(self, request):
        import hashlib

        from django.core.cache import cache

        from base.net import client_ip

        agente = (request.META.get('HTTP_USER_AGENT') or '').lower()
        if not agente or any(r in agente for r in ROBOS):
            return False
        visitante = hashlib.sha256(f'{client_ip(request)}|{agente}'.encode()).hexdigest()[:24]
        return cache.add(f'campanha:clique:{self.link.token}:{visitante}', 1, JANELA_DO_MESMO_CLIQUE)

    def get(self, request, token):
        from django.db.models import F
        from django.http import HttpResponseRedirect
        from django.utils import timezone

        from .models import CampaignLink

        self.link = CampaignLink.objects.filter(token=token).only('id', 'token', 'url').first()
        if self.link is None:
            return render(request, 'communications/link_indisponivel.html', status=404)
        if self._conta(request):
            CampaignLink.objects.filter(id=self.link.id).update(
                clicks=F('clicks') + 1, last_click_at=timezone.now(),
            )
        resposta = HttpResponseRedirect(self.link.url)
        resposta['Cache-Control'] = 'no-store'
        resposta['Referrer-Policy'] = 'no-referrer'
        return resposta

    def head(self, request, token):
        # O antivírus que confere o link costuma usar HEAD: leva, não conta.
        from django.http import HttpResponseRedirect

        from .models import CampaignLink

        link = CampaignLink.objects.filter(token=token).only('url').first()
        if link is None:
            return render(request, 'communications/link_indisponivel.html', status=404)
        return HttpResponseRedirect(link.url)
