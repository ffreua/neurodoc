"""Formulários das configurações de mensageria, na área do gestor.

Regra que vale para os dois: **o campo de segredo em branco não apaga o
segredo.** Reabrir a tela para mudar a porta do SMTP e salvar com a senha em
branco não pode zerar a senha — a tela mostra que existe uma senha guardada e
só a substitui quando algo novo é digitado.
"""

from django import forms

from .models import DoctorEmailSettings, MessagingSettings


class SmsSettingsForm(forms.ModelForm):
    api_key = forms.CharField(
        label='Chave da API do SMSDEV', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={
            'placeholder': 'Cole a chave aqui', 'autocomplete': 'off',
        }),
        help_text='Guardada cifrada. Deixe em branco para manter a chave atual.',
    )

    class Meta:
        model = MessagingSettings
        fields = ['sms_enabled', 'sms_sender_name']
        labels = {
            'sms_enabled': 'Enviar SMS por esta clínica',
            'sms_sender_name': 'Nome que aparece na mensagem',
        }
        help_texts = {
            'sms_sender_name': 'Como a clínica se identifica no texto. Ex.: Clínica Freua',
        }
        widgets = {
            'sms_sender_name': forms.TextInput(attrs={'placeholder': 'Ex.: Clínica Freua'}),
        }

    def clean(self):
        cleaned = super().clean()
        entered = (cleaned.get('api_key') or '').strip()
        if cleaned.get('sms_enabled') and not entered and not self.instance.has_api_key:
            self.add_error(
                'api_key',
                'Para ativar o SMS é preciso informar a chave da API do SMSDEV.',
            )
        return cleaned


class DoctorEmailSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        label='Senha do SMTP', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Guardada cifrada. Deixe em branco para manter a senha atual.',
    )

    class Meta:
        model = DoctorEmailSettings
        fields = [
            'enabled', 'from_name', 'from_email', 'reply_to',
            'smtp_host', 'smtp_port', 'smtp_user', 'use_tls', 'use_ssl',
        ]
        labels = {
            'enabled': 'Usar este remetente nos e-mails deste médico',
            'from_name': 'Nome do remetente',
            'from_email': 'E-mail do remetente',
            'reply_to': 'Responder para',
            'smtp_host': 'Servidor SMTP',
            'smtp_port': 'Porta',
            'smtp_user': 'Usuário do SMTP',
            'use_tls': 'Usar TLS (porta 587)',
            'use_ssl': 'Usar SSL (porta 465)',
        }
        help_texts = {
            'from_email': 'O endereço que o paciente vê como remetente.',
            'reply_to': 'Em branco, as respostas vão para o próprio remetente.',
            'smtp_host': 'Em branco, o e-mail sai pelo servidor da instalação com este remetente.',
        }
        widgets = {
            'from_name': forms.TextInput(attrs={'placeholder': 'Ex.: Dr. Fernando Freua'}),
            'from_email': forms.EmailInput(attrs={'placeholder': 'contato@clinica.com.br'}),
            'reply_to': forms.EmailInput(attrs={'placeholder': 'secretaria@clinica.com.br'}),
            'smtp_host': forms.TextInput(attrs={'placeholder': 'Ex.: smtp.gmail.com'}),
            'smtp_port': forms.NumberInput(attrs={'placeholder': '587', 'inputmode': 'numeric'}),
            'smtp_user': forms.TextInput(attrs={'placeholder': 'contato@clinica.com.br'}),
        }

    def clean(self):
        cleaned = super().clean()
        entered = (cleaned.get('smtp_password') or '').strip()
        host = (cleaned.get('smtp_host') or '').strip()
        user = (cleaned.get('smtp_user') or '').strip()
        if host and user and not entered and not self.instance.has_password:
            self.add_error(
                'smtp_password',
                'Informe a senha do SMTP para este usuário.',
            )
        return cleaned
