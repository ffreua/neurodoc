"""Formulário do provedor de IA da clínica.

Vale a mesma regra dos outros segredos do sistema: **campo em branco não
apaga o que está guardado.** Reabrir a tela para trocar o modelo e salvar
com a chave em branco não pode zerar a chave.
"""

from django import forms

from .models import AIProviderSettings
from .providers.catalog import PROVIDER_CHOICES, PROVIDERS


class AIProviderSettingsForm(forms.ModelForm):
    api_key = forms.CharField(
        label='Chave da API', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={
            'placeholder': 'Cole a chave aqui', 'autocomplete': 'off',
        }),
        help_text='Guardada cifrada. Deixe em branco para manter a chave atual.',
    )

    class Meta:
        model = AIProviderSettings
        fields = ['enabled', 'provider', 'base_url', 'model']
        labels = {
            'enabled': 'Usar IA nesta clínica',
            'provider': 'Provedor',
            'base_url': 'Endereço da API',
            'model': 'Modelo',
        }
        help_texts = {
            'base_url': 'Deixe em branco para usar o endereço padrão do provedor. '
                        'Preencha para servidor próprio (Ollama, vLLM) ou provedor '
                        'fora da lista.',
            'model': 'Escolhido da lista trazida do provedor. Salve a chave primeiro '
                     'e clique em "Carregar modelos".',
        }
        widgets = {
            'provider': forms.Select(choices=PROVIDER_CHOICES),
            'base_url': forms.TextInput(attrs={'placeholder': 'https://…/v1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provider'].choices = PROVIDER_CHOICES
        # O modelo vira lista quando já houve uma consulta ao provedor, e
        # segue como campo de texto antes disso — a tela precisa funcionar
        # no primeiro acesso, quando ainda não há chave nem lista.
        known = list(self.instance.available_models or [])
        current = (self.instance.model or '').strip()
        if current and current not in known:
            # O modelo em uso continua na lista mesmo que a última consulta
            # não o tenha trazido: aposentado no provedor, ele ainda é o que
            # está configurado, e sumir da tela esconderia o motivo do erro.
            known = [current] + known
        if known:
            self.fields['model'] = forms.ChoiceField(
                label='Modelo', required=False,
                choices=[('', '— escolha o modelo —')] + [(m, m) for m in known],
                help_text=self.fields['model'].help_text,
            )

    def clean(self):
        cleaned = super().clean()
        provider = cleaned.get('provider')
        entered = (cleaned.get('api_key') or '').strip()
        base_url = (cleaned.get('base_url') or '').strip()

        if provider == 'custom' and not base_url:
            self.add_error(
                'base_url',
                'Provedor fora da lista exige o endereço da API.',
            )
        elif provider and provider not in PROVIDERS:
            self.add_error('provider', 'Provedor desconhecido.')

        if cleaned.get('enabled'):
            if not entered and not self.instance.has_api_key:
                self.add_error('api_key', 'Para ativar a IA é preciso informar a chave da API.')
            if not (cleaned.get('model') or '').strip():
                self.add_error(
                    'model',
                    'Escolha o modelo antes de ativar. Sem modelo, o pedido falha no '
                    'provedor e o erro aparece para quem está atendendo.',
                )
        return cleaned
