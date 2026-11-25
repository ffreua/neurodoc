"""O aviso de status do WhatsApp, vindo da Twilio da clínica.

`/whatsapp/status/<token>/`: a Twilio posta aqui a situação de cada mensagem
(`StatusCallback`, que o envio põe em toda mensagem — a clínica não configura
nada). Fora de `/app/`, sem login e sem CSRF, porque quem posta é a Twilio.

Três conferências, nesta ordem, e nenhuma confia no que vem de fora:

1. o **token** da URL acha a configuração de uma clínica — e só isso: ele não
   autentica nada, só evita conferir assinatura contra todas as clínicas;
2. a **assinatura** `X-Twilio-Signature`, com o Auth Token daquela clínica,
   sobre a URL montada de `PUBLIC_BASE_URL` (nunca do `Host:`);
3. o `AccountSid` do aviso tem de ser o da clínica, e o `MessageSid` tem de
   ser de uma entrega **dela** (`aplicar_status_whatsapp` filtra pela
   clínica). Um aviso legítimo de uma conta não mexe em entrega de outra.

Responde rápido e sem corpo: a atualização é um `UPDATE` local, sem chamada
externa. 403 na assinatura errada, 404 no token desconhecido — e nenhum dos
dois diz qual era o esperado.
"""
import logging

from django.http import Http404, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from base.net import client_ip

logger = logging.getLogger(__name__)

#: Um aviso de status da Twilio tem poucas dezenas de campos curtos.
MAX_CORPO_AVISO = 16 * 1024

#: A ordem das situações do teste, para o aviso atrasado não regredir.
ORDEM_DO_TESTE = {
    'aceita pela twilio': 1, 'queued': 1, 'accepted': 1, 'sending': 2, 'sent': 3,
    'delivered': 4, 'read': 5, 'failed': 6, 'undelivered': 6,
}


@method_decorator(csrf_exempt, name='dispatch')
class StatusWhatsAppView(View):
    def post(self, request, token):
        from .models import WhatsAppTwilio
        from .reconciliation import aplicar_status_whatsapp
        from .whatsapp_twilio import assinatura_valida, url_do_status

        if len(request.body) > MAX_CORPO_AVISO:
            return HttpResponse(status=413)
        config = WhatsAppTwilio.objects.filter(token_webhook=token).first()
        if config is None or not config.tem_token:
            raise Http404
        try:
            auth_token = config.auth_token()
        except Exception:  # noqa: BLE001 -- chave-mestra indisponível
            logger.warning('whatsapp status: Auth Token ilegível para a clínica %s', config.tenant_id)
            return HttpResponse(status=503)
        assinatura = request.headers.get('X-Twilio-Signature', '')
        if not assinatura_valida(auth_token, url_do_status(config), request.POST, assinatura):
            logger.warning(
                'whatsapp status: assinatura recusada (clínica %s, ip=%s)',
                config.tenant_id, client_ip(request),
            )
            return HttpResponse(status=403)
        if request.POST.get('AccountSid', '') != config.account_sid:
            logger.warning('whatsapp status: AccountSid de outra conta (clínica %s)', config.tenant_id)
            return HttpResponse(status=403)

        sid = (request.POST.get('MessageSid') or '')[:100]
        situacao = (request.POST.get('MessageStatus') or '').lower()[:40]
        codigo = (request.POST.get('ErrorCode') or '')[:20]
        if not sid:
            return HttpResponse(status=400)
        if sid == config.teste_sid:
            # O envio de teste não é entrega: a situação vai para a tela de
            # configuração, que mostra se a mensagem chegou ao celular. Só
            # avança, porque a Twilio não garante a ordem dos avisos.
            if ORDEM_DO_TESTE.get(situacao, 0) < ORDEM_DO_TESTE.get(config.teste_status, 0):
                return HttpResponse(status=204)
            config.teste_status = situacao
            if codigo:
                from .whatsapp_twilio import traduzir_erro

                config.teste_erro = traduzir_erro(None, {'code': codigo})[1][:300]
            config.save(update_fields=['teste_status', 'teste_erro', 'updated_at'])
            return HttpResponse(status=204)
        aplicar_status_whatsapp(config.tenant_id, sid, situacao, codigo, 'wa_status')
        return HttpResponse(status=204)

    def get(self, request, token):
        raise Http404
