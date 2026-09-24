"""Configuração do provedor de IA — área do gestor da clínica.

Mesma porta das outras credenciais de provedor: `MANAGE_INTEGRATIONS`, que
é `owner` ou `manager`. A chave da API é credencial da organização, e quem
responde por ela é quem administra a clínica.

Segredo nunca volta para a tela. O que se mostra é a máscara, para conferir
que a chave gravada é a que se acha que é, sem exibi-la.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from audit.services import record_audit_event
from base.crypto import (
    SecretUnavailable, encrypt_secret, mask_secret, master_key_available,
)
from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.plans import has_clinical_ai, plan_label

from .forms import AIProviderSettingsForm
from .models import AIProviderSettings
from .providers.catalog import (
    PROVIDERS, ProviderProbeFailed, list_models, probe_model, resolve_base_url,
)


class ManagerRequiredView(CapabilityRequiredView):
    required_capability = Capability.MANAGE_INTEGRATIONS

    def dispatch(self, request, *args, **kwargs):
        from tenancy.models import Membership, MembershipStatus

        if request.access_context is None:
            from django.http import Http404

            raise Http404
        self.membership = Membership.objects.filter(
            id=request.access_context.membership_id,
            tenant_id=request.access_context.tenant_id,
            status=MembershipStatus.ACTIVE,
        ).select_related('tenant', 'user').first()
        if self.membership is None:
            from django.http import Http404

            raise Http404
        # Plano sem IA: le, nao escreve.
        #
        # Nao e 404 como o resto das recusas deste arquivo, e a diferenca e
        # deliberada. Quem abre esta tela e o dono ou o gestor -- quem
        # contrataria o plano. Esconder a tela deles ensinaria que o recurso
        # nao existe; mostra-la explicando que o plano nao o inclui responde
        # a pergunta que a pessoa veio fazer.
        #
        # O que nao se pode e deixar gravar: uma chave de provedor guardada
        # numa clinica onde a IA nunca vai rodar e uma armadilha -- a tela
        # diria "configurado" e nada funcionaria, e o motivo estaria em
        # outro lugar. Por isso o bloqueio e por **verbo HTTP**, num lugar
        # so, igual ao que `TenantMiddleware` faz com a clinica suspensa.
        #
        # A capacidade e conferida **antes** do plano, e a ordem nao e
        # detalhe: quem nao tem `MANAGE_INTEGRATIONS` precisa receber o 404
        # da base, e nao este 403 -- um 403 aqui contaria a uma secretaria
        # que a tela existe, que e exatamente o que a recusa por 404 evita
        # no resto de `/app/`. Escrito ao contrario, o roteiro pegou: o
        # medico sem papel administrativo levava 403 no POST e 404 no GET
        # da mesma rota.
        if (
            request.method not in ('GET', 'HEAD')
            and request.access_context.can(self.required_capability)
            and not self.ai_contratada
        ):
            from django.http import HttpResponseForbidden

            return HttpResponseForbidden(
                f'O plano {plan_label(self.membership.tenant.plan)} não inclui o '
                f'apoio clínico por IA.'
            )
        return super().dispatch(request, *args, **kwargs)

    @property
    def ai_contratada(self):
        """Se o plano desta clinica inclui a IA.

        `self.membership` ja vem com `select_related('tenant')`, entao isto
        nao acrescenta consulta.
        """
        return has_clinical_ai(self.membership.tenant.plan)

    @property
    def tenant_id(self):
        return self.request.access_context.tenant_id


def settings_for(tenant_id):
    row, _ = AIProviderSettings.objects.get_or_create(tenant_id=tenant_id)
    return row


def _live_key(row, request=None):
    """A chave a usar numa consulta ao provedor.

    Aceita a chave recém-digitada no formulário para que "Carregar modelos"
    funcione **antes** de salvar: exigir salvar primeiro obrigaria a gravar
    cifrada uma chave que ainda não se sabe se é válida, e a desfazer isso
    depois quando não fosse.
    """
    typed = (request.POST.get('api_key') or '').strip() if request is not None else ''
    if typed:
        return typed
    if not row.has_api_key:
        return ''
    return row.api_key()


class AISettingsView(ManagerRequiredView):
    def _context(self, request, **overrides):
        from django.conf import settings as django_settings

        # O tenant sai do `request` recebido, e não de `self.tenant_id`:
        # as views de gravação re-renderizam a tela chamando
        # `AISettingsView()._context(request, form=form)` numa instância
        # que nunca passou por `dispatch` e portanto não tem `self.request`.
        row = settings_for(request.access_context.tenant_id)
        context = {
            'ai': row,
            'form': AIProviderSettingsForm(instance=row),
            'providers': PROVIDERS,
            'provider_meta': PROVIDERS.get(row.provider, {}),
            'resolved_base_url': resolve_base_url(row.provider, row.base_url),
            'ai_globally_enabled': django_settings.AI_ENABLED,
            'platform_provider': django_settings.AI_PROVIDER,
            'platform_model': django_settings.AI_MODEL,
            'has_master_key': master_key_available(),
            'model_count': len(row.available_models or []),
            # Padrao "tem IA", sobrescrito pelo `get` abaixo.
            #
            # As views de gravacao re-renderizam esta tela chamando
            # `AISettingsView()._context(request, form=form)` numa
            # instancia que nunca passou por `dispatch` e nao tem
            # `self.membership`. Calcular aqui daria `AttributeError` no
            # caminho de erro do formulario. O padrao e seguro porque
            # gravar ja e recusado em `dispatch` quando o plano nao inclui
            # a IA: quem chega a re-renderizar, contratou.
            'ai_contratada': True,
            'plano_label': '',
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'ai/settings.html', self._context(
            request,
            ai_contratada=self.ai_contratada,
            plano_label=plan_label(self.membership.tenant.plan),
        ))


class AISettingsSaveView(ManagerRequiredView):
    def post(self, request):
        row = settings_for(self.tenant_id)
        # O provedor de antes é lido agora, antes de validar: `ModelForm`
        # com `instance` escreve os dados enviados no próprio objeto durante
        # `is_valid()`, então `form.instance` e `row` são o mesmo objeto.
        # Comparar depois compararia o valor novo com ele mesmo, e a troca
        # de provedor passaria despercebida — deixando na tela a lista de
        # modelos do provedor anterior, que o novo não conhece.
        previous_provider = row.provider
        form = AIProviderSettingsForm(request.POST, instance=row)
        if not form.is_valid():
            return render(request, 'ai/settings.html',
                          AISettingsView()._context(request, form=form))
        entered = (form.cleaned_data.get('api_key') or '').strip()
        saved = form.save(commit=False)
        if entered:
            if not master_key_available():
                messages.error(
                    request,
                    'Não há chave-mestra configurada (SECRETS_MASTER_KEY), então a chave '
                    'da API não pode ser guardada cifrada. Configure-a antes.',
                )
                return redirect('ai-admin:settings')
            saved.api_key_ciphertext, saved.api_key_metadata = encrypt_secret(entered)
            saved.api_key_hint = mask_secret(entered)
        if saved.provider != previous_provider:
            # Trocar de provedor invalida a lista de modelos: os
            # identificadores não são compartilhados entre eles, e manter a
            # lista antiga ofereceria um modelo que o provedor novo não
            # conhece.
            saved.available_models = []
            saved.models_synced_at = None
        saved.tenant_id = self.tenant_id
        saved.updated_by = self.membership
        saved.save()
        record_audit_event(
            request.user, self.tenant_id, 'ai.provider_settings_updated',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
            # A chave não entra no log, nem mascarada.
            integrity_metadata={
                'provider': saved.provider, 'model': saved.model,
                'enabled': saved.enabled, 'key_changed': bool(entered),
            },
        )
        messages.success(request, 'Configuração de IA salva.')
        return redirect('ai-admin:settings')


class AIModelsRefreshView(ManagerRequiredView):
    """Pergunta ao provedor quais modelos ele oferece para esta chave."""

    def post(self, request):
        row = settings_for(self.tenant_id)
        provider = request.POST.get('provider') or row.provider
        base_url = request.POST.get('base_url') or row.base_url
        try:
            key = _live_key(row, request)
        except SecretUnavailable as exc:
            messages.error(request, f'A chave guardada não pôde ser aberta: {exc}')
            return redirect('ai-admin:settings')

        try:
            models = list_models(provider, key, base_url)
        except ProviderProbeFailed as exc:
            messages.error(request, str(exc))
            return redirect('ai-admin:settings')

        if not models:
            messages.warning(
                request,
                'O provedor aceitou a chave mas não devolveu modelo nenhum. '
                'Confira se a conta tem acesso a algum modelo.',
            )
            return redirect('ai-admin:settings')

        from django.utils import timezone

        row.provider = provider
        row.base_url = (base_url or '').strip()
        row.available_models = models
        row.models_synced_at = timezone.now()
        row.updated_by = self.membership
        row.save(update_fields=[
            'provider', 'base_url', 'available_models', 'models_synced_at',
            'updated_by', 'updated_at',
        ])
        record_audit_event(
            request.user, self.tenant_id, 'ai.models_refreshed',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
            integrity_metadata={'provider': provider, 'count': len(models)},
        )
        # Não se afirma aqui que a chave foi aceita.
        #
        # O `/models` de alguns provedores é público — o do OpenRouter
        # responde a lista inteira sem credencial nenhuma. Dizer "a chave foi
        # aceita" porque a lista chegou daria por verificada uma chave
        # inválida, e o erro só apareceria quando um médico pedisse um
        # resumo. Quem prova a chave é o teste do modelo, que consome uma
        # chamada de verdade.
        messages.success(
            request,
            f'{len(models)} modelo(s) disponíveis em '
            f'{PROVIDERS.get(provider, {}).get("label", provider)}. '
            'Escolha o modelo, salve e use "Testar o modelo" para confirmar a chave — '
            'a lista de modelos é pública em alguns provedores e não prova a credencial.',
        )
        return redirect('ai-admin:settings')


class AITestView(ManagerRequiredView):
    """Manda uma pergunta mínima ao modelo escolhido.

    Carregar a lista prova a chave; isto prova o **modelo**. São falhas
    diferentes: chave errada e identificador de modelo aposentado dão o
    mesmo erro genérico para quem pede um resumo no meio do atendimento, e
    quem resolve cada uma é diferente.

    A pergunta é fixa e sem conteúdo clínico. Testar com dado de paciente
    seria mandar prontuário a um provedor que ainda não se sabe se funciona.
    """

    def post(self, request):
        row = settings_for(self.tenant_id)
        # Testa o que está **na tela**, não o que está gravado.
        #
        # Escolher o modelo, clicar em testar e receber "salve antes" faz o
        # botão recusar exatamente o que se quer experimentar. Testar existe
        # para descobrir se a combinação funciona **antes** de gravá-la — é o
        # mesmo motivo pelo qual "Carregar modelos" já aceita a chave
        # recém-digitada.
        provider = request.POST.get('provider') or row.provider
        base_url = request.POST.get('base_url') if 'base_url' in request.POST else row.base_url
        model = (request.POST.get('model') or row.model or '').strip()
        if not model:
            messages.warning(
                request,
                'Escolha um modelo antes de testar. Se a lista está vazia, use '
                '"Carregar modelos" primeiro.',
            )
            return redirect('ai-admin:settings')
        try:
            key = _live_key(row, request)
        except SecretUnavailable as exc:
            messages.error(request, f'A chave guardada não pôde ser aberta: {exc}')
            return redirect('ai-admin:settings')
        if not key:
            messages.warning(request, 'Informe a chave da API antes de testar.')
            return redirect('ai-admin:settings')

        try:
            answer = probe_model(provider, key, model, base_url)
        except ProviderProbeFailed as exc:
            record_audit_event(
                request.user, self.tenant_id, 'ai.provider_tested',
                object_type='tenant', object_id=self.tenant_id, outcome='failure',
                integrity_metadata={'provider': provider, 'model': model},
            )
            messages.error(request, str(exc))
            return redirect('ai-admin:settings')

        record_audit_event(
            request.user, self.tenant_id, 'ai.provider_tested',
            object_type='tenant', object_id=self.tenant_id, outcome='success',
            integrity_metadata={'provider': provider, 'model': model},
        )
        saved_note = '' if model == row.model else ' Salve para passar a usar este modelo.'
        messages.success(
            request,
            f'O modelo {model} respondeu: “{answer or "(resposta vazia)"}”. '
            f'Nenhum dado de paciente foi enviado neste teste.{saved_note}',
        )
        return redirect('ai-admin:settings')
