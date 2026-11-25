"""A tela do WhatsApp pela Twilio da clínica (`/app/org/mensageria/whatsapp-twilio/`).

Quem configura é quem já configura SMS e e-mail (`MANAGE_INTEGRATIONS`: dono
e gestor). **Nenhuma destas views fala com a Twilio**: verificar e testar
enfileiram tarefas no worker (CLAUDE.md §2), e a tela recarrega sozinha
enquanto a verificação corre. Decisões em `docs/governance/whatsapp-twilio.md`.
"""
import re

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from audit.services import record_audit_event
from base.crypto import encrypt_secret, mask_secret, master_key_available

from .admin_views import ManagerRequiredView
from .forms import WhatsAppTwilioForm
from . import whatsapp_twilio as wa

PADRAO_CONTENT_SID = re.compile(r'HX[0-9a-fA-F]{32}')


def _tela():
    return redirect('messaging:whatsapp-twilio')


#: Depois disto sem resposta, a tela para de esperar (worker parado, fila
#: perdida) e mostra o botão de novo, em vez de recarregar para sempre.
ESPERA_DA_VERIFICACAO = timezone.timedelta(minutes=3)


def _verificando(config):
    """A verificação pedida ainda não terminou (e ainda vale esperar por ela)?"""
    return bool(
        config and config.verificacao_pedida_em
        and timezone.now() - config.verificacao_pedida_em < ESPERA_DA_VERIFICACAO
        and (
            config.verificacao_concluida_em is None
            or config.verificacao_concluida_em < config.verificacao_pedida_em
        )
    )


def _pedir_verificacao(request, config):
    from .tasks import verificar_whatsapp_twilio_task

    config.verificacao_pedida_em = timezone.now()
    config.save(update_fields=['verificacao_pedida_em', 'updated_at'])
    tenant_id, user_id = config.tenant_id, request.user.id
    transaction.on_commit(
        lambda: verificar_whatsapp_twilio_task.delay(str(tenant_id), user_id),
    )


class WhatsAppTwilioView(ManagerRequiredView):
    def get(self, request, form=None):
        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id)
        modelos = wa.modelos_da_clinica(tenant_id)
        liberado = wa.liberado_na_instalacao()
        codigo = wa.estado(config, modelos, liberado)
        rotulo, classe = wa.ESTADOS[codigo]
        if form is None:
            form = WhatsAppTwilioForm(
                initial={
                    'account_sid': getattr(config, 'account_sid', ''),
                    'numero': getattr(config, 'numero', ''),
                    'messaging_service_sid': getattr(config, 'messaging_service_sid', ''),
                },
                tem_token=bool(config and config.tem_token),
            )
        linhas = [
            {
                'evento': m.evento, 'info': wa.EVENTOS[m.evento], 'modelo': m,
                'aprovado': wa.modelo_aprovado(m),
            }
            for m in modelos
        ]
        return render(request, 'communications/whatsapp_twilio.html', {
            'config': config,
            'form': form,
            'estado': codigo,
            'estado_rotulo': rotulo,
            'estado_classe': classe,
            'liberado': liberado,
            'linhas': linhas,
            'verificando': _verificando(config),
            'has_master_key': master_key_available(),
            'pode_testar': bool(
                config and config.verificado_em and liberado
                and any(linha['aprovado'] for linha in linhas)
            ),
        })


class WhatsAppCredenciaisSaveView(ManagerRequiredView):
    def post(self, request):
        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id, criar=True)
        form = WhatsAppTwilioForm(request.POST, tem_token=config.tem_token)
        if not form.is_valid():
            return WhatsAppTwilioView.get(self, request, form=form)
        dados = form.cleaned_data
        token = dados['auth_token']
        if token and not master_key_available():
            messages.error(
                request,
                'A guarda de credenciais ainda não foi liberada pela administração do '
                'sistema, então o Auth Token não pode ser salvo. Fale com o suporte.',
            )
            return _tela()
        mudou = sorted(
            campo for campo in ('account_sid', 'numero', 'messaging_service_sid')
            if getattr(config, campo) != dados[campo]
        )
        for campo in mudou:
            setattr(config, campo, dados[campo])
        if token:
            config.auth_token_ciphertext, config.auth_token_metadata = encrypt_secret(token)
            config.auth_token_hint = mask_secret(token)
            mudou.append('auth_token')
        if mudou:
            # Credencial ou número novo: o que foi verificado antes não vale
            # mais. Volta a "Pendente" e para de enviar até verificar de novo.
            config.invalidar_verificacao()
        config.updated_by = self.membership
        config.save()
        record_audit_event(
            request.user, tenant_id, 'communications.whatsapp_config_atualizada',
            object_type='tenant', object_id=tenant_id, outcome='success',
            # Os **nomes** dos campos que mudaram; nunca o token, nem o número.
            integrity_metadata={'campos': mudou},
        )
        if mudou:
            _pedir_verificacao(request, config)
            messages.success(
                request,
                'Credenciais salvas. A verificação na Twilio começou e o resultado '
                'aparece nesta tela em alguns segundos.',
            )
        else:
            messages.info(request, 'Nada mudou nas credenciais.')
        return _tela()


class WhatsAppVerificarView(ManagerRequiredView):
    def post(self, request):
        config = wa.config_da_clinica(request.access_context.tenant_id)
        if config is None or not config.tem_credenciais:
            messages.error(request, 'Salve as credenciais antes de verificar.')
            return _tela()
        _pedir_verificacao(request, config)
        messages.info(request, 'Verificação pedida. O resultado aparece nesta tela em alguns segundos.')
        return _tela()


class WhatsAppModelosSaveView(ManagerRequiredView):
    """Grava o ContentSid e a chave de cada ocasião.

    Ligar só vale com o modelo aprovado e conferido: a caixa marcada de um
    modelo ainda não conferido fica gravada, mas `para_enviar` só usa o que a
    verificação aprovou — e a tela diz por quê.
    """

    def post(self, request):
        from .models import WhatsAppModelo

        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id)
        erros, trocados, ligados = [], [], []
        for evento, info in wa.EVENTOS.items():
            sid = (request.POST.get(f'sid_{evento}') or '').strip()
            if sid and not PADRAO_CONTENT_SID.fullmatch(sid):
                erros.append(
                    f'{info["rotulo"]}: o identificador do modelo tem 34 caracteres e começa com HX.',
                )
                continue
            modelo, _ = WhatsAppModelo.objects.get_or_create(tenant_id=tenant_id, evento=evento)
            ligado = bool(request.POST.get(f'ligado_{evento}')) and bool(sid)
            if modelo.content_sid != sid:
                modelo.content_sid = sid
                modelo.conferido_em = None
                modelo.aprovacao = ''
                modelo.variaveis = None
                modelo.erro_texto = ''
                trocados.append(evento)
            modelo.ligado = ligado
            modelo.save()
            if ligado:
                ligados.append(evento)
        for erro in erros:
            messages.error(request, erro)
        record_audit_event(
            request.user, tenant_id, 'communications.whatsapp_modelos_atualizados',
            object_type='tenant', object_id=tenant_id, outcome='success',
            integrity_metadata={'trocados': trocados, 'ligados': ligados},
        )
        if trocados and config is not None and config.tem_credenciais:
            _pedir_verificacao(request, config)
            messages.success(
                request, 'Modelos salvos. A conferência na Twilio começou; o resultado '
                         'aparece ao lado de cada ocasião.',
            )
        elif not erros:
            messages.success(request, 'Escolha das ocasiões salva.')
        return redirect(reverse('messaging:whatsapp-twilio') + '#modelos')


class WhatsAppAtivarView(ManagerRequiredView):
    """Ativa ou suspende o envio pela clínica, sem apagar nada."""

    def post(self, request):
        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id)
        ativar = request.POST.get('acao') == 'ativar'
        if config is None or not config.tem_credenciais:
            messages.error(request, 'Salve e verifique as credenciais antes.')
            return _tela()
        if ativar and not config.verificado_em:
            messages.error(
                request,
                'Só dá para ativar depois de a verificação na Twilio passar. Use '
                '"Verificar agora" e corrija o que ela apontar.',
            )
            return _tela()
        config.ativo = ativar
        config.updated_by = self.membership
        config.save(update_fields=['ativo', 'updated_by', 'updated_at'])
        record_audit_event(
            request.user, tenant_id,
            'communications.whatsapp_ativado' if ativar else 'communications.whatsapp_suspenso',
            object_type='tenant', object_id=tenant_id, outcome='success',
        )
        messages.success(
            request,
            'WhatsApp ativado nesta clínica.' if ativar
            else 'WhatsApp suspenso. Nada mais sai por ele até reativar; as credenciais ficam guardadas.',
        )
        return _tela()


class WhatsAppTesteView(ManagerRequiredView):
    def post(self, request):
        from .tasks import enviar_teste_whatsapp_twilio_task

        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id)
        evento = request.POST.get('evento', '')
        telefone = request.POST.get('telefone', '')
        if evento not in wa.EVENTOS:
            messages.error(request, 'Escolha a ocasião cujo modelo será testado.')
            return _tela()
        if wa.numero_e164(telefone) is None:
            messages.error(request, 'Informe um celular válido, com DDD, para receber o teste.')
            return _tela()
        if not (config and config.verificado_em and wa.liberado_na_instalacao()):
            messages.error(
                request,
                'O teste precisa da conta verificada e do canal liberado pela administração '
                'do sistema.',
            )
            return _tela()
        transaction.on_commit(
            lambda: enviar_teste_whatsapp_twilio_task.delay(
                str(tenant_id), request.user.id, evento, telefone,
            ),
        )
        messages.info(
            request,
            'Teste enviado à fila. A situação (aceita, entregue, lida ou o erro) aparece '
            'no cartão "Envio de teste" em instantes.',
        )
        return redirect(reverse('messaging:whatsapp-twilio') + '#teste')


class WhatsAppRemoverView(ManagerRequiredView):
    """Apaga as credenciais e desliga o canal desta clínica.

    Os modelos ficam com o identificador (não é segredo) e desligados: quem
    voltar a configurar não precisa digitar os HX… de novo, mas nada sai sem
    escolher as ocasiões outra vez.
    """

    def post(self, request):
        from .models import WhatsAppModelo

        tenant_id = request.access_context.tenant_id
        config = wa.config_da_clinica(tenant_id)
        if config is not None:
            config.account_sid = ''
            config.auth_token_ciphertext = ''
            config.auth_token_metadata = {}
            config.auth_token_hint = ''
            config.numero = ''
            config.messaging_service_sid = ''
            config.ativo = False
            config.invalidar_verificacao()
            config.verificacao_pedida_em = None
            config.teste_sid = ''
            config.teste_status = ''
            config.teste_erro = ''
            config.updated_by = self.membership
            config.save()
            WhatsAppModelo.objects.filter(tenant_id=tenant_id).update(ligado=False)
        record_audit_event(
            request.user, tenant_id, 'communications.whatsapp_credenciais_removidas',
            object_type='tenant', object_id=tenant_id, outcome='success',
        )
        messages.success(
            request,
            'Credenciais apagadas e WhatsApp desligado nesta clínica. Para encerrar de vez, '
            'troque também o Auth Token no Console da Twilio.',
        )
        return _tela()
