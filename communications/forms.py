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


class MarketingCampaignForm(forms.ModelForm):
    """Campanha de comunicação em massa.

    O rodapé com o link de descadastro **não** é campo: é acrescentado no
    envio. Quem escreve não deve poder removê-lo por esquecimento nem por
    escolha — é ele que torna a revogação tão fácil quanto o consentimento.
    """

    class Meta:
        from .models import MarketingCampaign

        model = MarketingCampaign
        fields = ['subject', 'body_html', 'body_text', 'per_minute']
        labels = {
            'subject': 'Assunto',
            'body_html': 'Mensagem em HTML (opcional)',
            'body_text': 'Mensagem em texto simples',
            'per_minute': 'Envios por minuto',
        }
        help_texts = {
            'subject': 'Aparece na caixa de entrada. Sem conteúdo clínico e sem o '
                       'nome de quem recebe.',
            'body_html': 'Cole o HTML com CSS (bloco <style> ou style= nas marcas). '
                         'Script, formulário e iframe são retirados; imagem só de '
                         'endereço https://. O rodapé com o link de descadastro é '
                         'acrescentado no envio.',
            'body_text': 'Obrigatória se não houver HTML. Com HTML, é a versão para '
                         'quem não vê HTML — em branco, sai gerada do próprio HTML. '
                         'O rodapé com o link de descadastro é acrescentado no envio.',
            'per_minute': 'Comece baixo. Provedor que recebe um lote grande de um '
                          'remetente novo trata as mensagens seguintes como spam, e '
                          'recuperar a reputação de um domínio leva semanas.',
        }
        widgets = {
            'subject': forms.TextInput(attrs={'placeholder': 'Ex.: Campanha de vacinação 2026'}),
            'body_html': forms.Textarea(attrs={
                'rows': 14, 'spellcheck': 'false', 'class': 'font-monospace fs-12',
                'placeholder': '<table width="100%">…</table>',
            }),
            'body_text': forms.Textarea(attrs={'rows': 8}),
            'per_minute': forms.NumberInput(attrs={'min': 1, 'inputmode': 'numeric'}),
        }

    def clean_per_minute(self):
        from .marketing import MAX_PER_MINUTE

        valor = self.cleaned_data['per_minute']
        if valor < 1:
            raise forms.ValidationError('Informe ao menos 1 envio por minuto.')
        if valor > MAX_PER_MINUTE:
            raise forms.ValidationError(
                f'O máximo é {MAX_PER_MINUTE} por minuto. Acima disso um erro de '
                'configuração vira problema de reputação antes de alguém perceber.'
            )
        return valor

    def clean_body_html(self):
        from .email_html import MAX_HTML, limpar_html

        bruto = (self.cleaned_data.get('body_html') or '').strip()
        if not bruto:
            return ''
        css, corpo = limpar_html(bruto)
        if not corpo:
            raise forms.ValidationError(
                'Nada do HTML sobrou depois da limpeza. Confira se ele tem conteúdo '
                'visível (texto ou imagem https://) e não só script ou estilo.'
            )
        # Grava-se o que vai sair, e não o que foi colado: a tela de detalhe,
        # a prévia e o envio leem a mesma coisa, e o que a limpeza retirou não
        # fica guardado esperando outro caminho de leitura.
        limpo = (f'<style>{css}</style>\n' if css else '') + corpo
        if len(limpo) > MAX_HTML:
            raise forms.ValidationError(
                f'O HTML passa de {MAX_HTML // 1000} mil caracteres. O Gmail corta a '
                'mensagem acima de ~100 KB e esconde o fim — justamente onde fica o '
                'link de descadastro. Reduza o HTML (imagens vão por endereço, não '
                'embutidas).'
            )
        return limpo

    def clean(self):
        dados = super().clean()
        if not (dados.get('body_html') or '').strip() and not (dados.get('body_text') or '').strip():
            if 'body_html' not in self.errors:
                self.add_error('body_text', 'Escreva a mensagem em texto simples, em HTML, ou nos dois.')
        return dados

    def clean_body_text(self):
        texto = self.cleaned_data['body_text']
        if 'descadastr' in texto.lower() or 'unsubscribe' in texto.lower():
            # Aviso, não recusa: o texto pode citar o assunto legitimamente.
            # O que não pode é a pessoa achar que precisa escrever o link.
            self.add_error(None, forms.ValidationError(
                'O link de descadastro é acrescentado automaticamente no rodapé — '
                'não é preciso escrevê-lo. Confira se o texto não vai duplicá-lo.',
            ))
        return texto


class WhatsAppTextForm(forms.ModelForm):
    """O texto do lembrete pelo WhatsApp da recepção (1.39).

    Em branco é o texto padrão do sistema, e não "sem mensagem": a clínica
    que nunca abriu esta tela já tem o botão funcionando na agenda.
    """

    class Meta:
        model = MessagingSettings
        fields = ['whatsapp_texto']
        labels = {'whatsapp_texto': 'Texto da mensagem'}
        widgets = {
            'whatsapp_texto': forms.Textarea(attrs={'rows': 8}),
        }

    def __init__(self, *args, **kwargs):
        from .whatsapp import MAX_CARACTERES

        super().__init__(*args, **kwargs)
        campo = self.fields['whatsapp_texto']
        campo.max_length = MAX_CARACTERES
        campo.widget.attrs['maxlength'] = str(MAX_CARACTERES)
        campo.help_text = (
            f'Até {MAX_CARACTERES} caracteres. Deixe em branco para usar o texto padrão do sistema.'
        )
        # A caixa nasce com o texto padrão, para a clínica editar em vez de
        # escrever do zero. Salvo sem mudança, continua sendo "o padrão"
        # (ver `clean_whatsapp_texto`), e não vira uma cópia que deixaria de
        # acompanhar uma melhoria futura do texto do sistema.
        if not self.is_bound and self.instance.pk and not (self.instance.whatsapp_texto or '').strip():
            from .whatsapp import padrao_da_clinica

            self.initial['whatsapp_texto'] = padrao_da_clinica(self.instance.tenant)

    def clean_whatsapp_texto(self):
        from .whatsapp import MAX_CARACTERES, TEXTO_PADRAO, TEXTO_PADRAO_SEM_ENDERECO, campos_desconhecidos

        # O navegador manda a quebra de linha da caixa como CR+LF.
        texto = (self.cleaned_data.get('whatsapp_texto') or '').replace('\r\n', '\n').strip()
        if texto in (TEXTO_PADRAO, TEXTO_PADRAO_SEM_ENDERECO):
            return ''
        if len(texto) > MAX_CARACTERES:
            raise forms.ValidationError(f'O texto passa de {MAX_CARACTERES} caracteres.')
        desconhecidos = campos_desconhecidos(texto)
        if desconhecidos:
            lista = ', '.join('{' + nome + '}' for nome in desconhecidos)
            raise forms.ValidationError(
                f'Campo que o sistema não conhece: {lista}. Use só os campos da lista ao lado, '
                'escritos exatamente como aparecem.'
            )
        return texto


class WhatsAppTwilioForm(forms.Form):
    """As credenciais da conta Twilio da clínica.

    Formato conferido aqui (o que se confere sem perguntar à Twilio); se a
    credencial **vale**, só a verificação no worker diz. O Auth Token em
    branco mantém o guardado, como a senha do SMTP.
    """

    account_sid = forms.CharField(
        label='Account SID', max_length=40,
        widget=forms.TextInput(attrs={'placeholder': 'AC…', 'autocomplete': 'off', 'spellcheck': 'false'}),
        help_text='Na página inicial do Console da Twilio, em "Account Info". Começa com AC.',
    )
    auth_token = forms.CharField(
        label='Auth Token', required=False, max_length=64,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'off'}),
        help_text='Também em "Account Info" (clique em "Show" para copiar). Guardado cifrado; '
                  'deixe em branco para manter o atual.',
    )
    numero = forms.CharField(
        label='Número do WhatsApp da clínica', max_length=20,
        widget=forms.TextInput(attrs={'placeholder': '+55 11 98765-4321', 'autocomplete': 'off'}),
        help_text='O número cadastrado em WhatsApp Senders na Twilio, com DDD.',
    )
    messaging_service_sid = forms.CharField(
        label='Messaging Service SID (opcional)', required=False, max_length=40,
        widget=forms.TextInput(attrs={'placeholder': 'MG…', 'autocomplete': 'off', 'spellcheck': 'false'}),
        help_text='Só se a Twilio exigir um Messaging Service para o envio. Na dúvida, deixe em branco.',
    )

    def __init__(self, *args, tem_token=False, **kwargs):
        self.tem_token = tem_token
        super().__init__(*args, **kwargs)

    def clean_account_sid(self):
        import re

        valor = (self.cleaned_data.get('account_sid') or '').strip()
        if not re.fullmatch(r'AC[0-9a-fA-F]{32}', valor):
            raise forms.ValidationError(
                'O Account SID tem 34 caracteres e começa com AC. Copie de novo de "Account Info".',
            )
        return valor

    def clean_auth_token(self):
        import re

        valor = (self.cleaned_data.get('auth_token') or '').strip()
        if not valor and not self.tem_token:
            raise forms.ValidationError('Informe o Auth Token.')
        if valor and not re.fullmatch(r'[0-9a-fA-F]{32}', valor):
            raise forms.ValidationError(
                'O Auth Token tem 32 letras e números. Copie de novo de "Account Info".',
            )
        return valor

    def clean_numero(self):
        from .whatsapp_twilio import numero_e164

        valor = numero_e164(self.cleaned_data.get('numero'))
        if valor is None:
            raise forms.ValidationError(
                'Número inválido. Use o número com DDD (e com +55, ou o código do país).',
            )
        return valor

    def clean_messaging_service_sid(self):
        import re

        valor = (self.cleaned_data.get('messaging_service_sid') or '').strip()
        if valor and not re.fullmatch(r'MG[0-9a-fA-F]{32}', valor):
            raise forms.ValidationError('O Messaging Service SID tem 34 caracteres e começa com MG.')
        return valor
