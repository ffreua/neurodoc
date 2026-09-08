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


class ClinicEmailSettingsForm(forms.ModelForm):
    """Servidor de e-mail da clínica — o remetente padrão de todo mundo.

    Mesmo desenho do formulário por médico, e de propósito: quem já
    configurou um reconhece o outro. A diferença é o alcance — este vale
    para a clínica inteira, e o do médico só sobrescreve quando ele quiser
    que o e-mail saia no nome dele.
    """

    smtp_password = forms.CharField(
        label='Senha do SMTP', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Guardada cifrada. Deixe em branco para manter a senha atual.',
    )

    class Meta:
        model = MessagingSettings
        fields = [
            'email_enabled', 'email_from_name', 'email_from_address', 'email_reply_to',
            'smtp_host', 'smtp_port', 'smtp_user', 'smtp_use_tls', 'smtp_use_ssl',
        ]
        labels = {
            'email_enabled': 'Enviar e-mail por este servidor',
            'email_from_name': 'Nome do remetente',
            'email_from_address': 'E-mail do remetente',
            'email_reply_to': 'Responder para',
            'smtp_host': 'Servidor SMTP',
            'smtp_port': 'Porta',
            'smtp_user': 'Usuário do SMTP',
            'smtp_use_tls': 'Usar TLS (porta 587)',
            'smtp_use_ssl': 'Usar SSL (porta 465)',
        }
        help_texts = {
            'email_from_address': 'O endereço que o paciente vê como remetente.',
            'email_reply_to': 'Em branco, as respostas vão para o próprio remetente.',
            'smtp_host': 'Em branco, o e-mail sai pelo servidor da instalação com este remetente.',
        }
        widgets = {
            'email_from_name': forms.TextInput(attrs={'placeholder': 'Ex.: Clínica Freua'}),
            'email_from_address': forms.EmailInput(attrs={'placeholder': 'contato@clinica.com.br'}),
            'email_reply_to': forms.EmailInput(attrs={'placeholder': 'secretaria@clinica.com.br'}),
            'smtp_host': forms.TextInput(attrs={'placeholder': 'Ex.: smtp.gmail.com'}),
            'smtp_port': forms.NumberInput(attrs={'placeholder': '587', 'inputmode': 'numeric'}),
            'smtp_user': forms.TextInput(attrs={'placeholder': 'contato@clinica.com.br'}),
        }

    def clean(self):
        cleaned = super().clean()
        entered = (cleaned.get('smtp_password') or '').strip()
        host = (cleaned.get('smtp_host') or '').strip()
        user = (cleaned.get('smtp_user') or '').strip()
        if host and user and not entered and not self.instance.has_smtp_password:
            self.add_error('smtp_password', 'Informe a senha do SMTP para este usuário.')
        if cleaned.get('smtp_use_tls') and cleaned.get('smtp_use_ssl'):
            self.add_error(
                'smtp_use_ssl',
                'TLS e SSL são alternativos: escolha um. A porta 587 costuma usar TLS; a 465, SSL.',
            )
        if cleaned.get('email_enabled') and not (cleaned.get('email_from_address') or '').strip():
            self.add_error('email_from_address', 'Informe o e-mail remetente da clínica.')
        return cleaned


class EmailTestForm(forms.Form):
    """Para onde mandar o e-mail de teste.

    O endereço é digitado a cada teste, e não guardado: testar o envio é
    algo que se faz ao configurar e ao investigar um problema, e o endereço
    certo muda conforme o caso — a caixa do gestor, a de um paciente que
    reclamou, uma de outro provedor para ver se cai em spam.
    """

    to_email = forms.EmailField(
        label='Enviar teste para', widget=forms.EmailInput(attrs={
            'placeholder': 'seu-email@exemplo.com', 'autocomplete': 'off',
        }),
    )
