from django.db import models
from django.db.models import Q

from base.models import TenantModel


def _remetente(nome, endereco):
    """`"Nome" <endereco>`, com o nome entre aspas.

    Concatenado sem aspas (auditoria de 2026-11-11), um nome com vírgula ou
    aspas — "Clínica X, Neurologia" — era lido como dois endereços ou como
    um inválido, e todo e-mail daquele remetente falhava. Aspas e barra
    invertida do próprio nome são escapadas; o acento fica, e quem o
    codifica para o cabeçalho é o Django, como sempre fez.
    """
    seguro = nome.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{seguro}" <{endereco}>'


class DeliveryChannel(models.TextChoices):
    EMAIL = 'email', 'E-mail'
    SMS = 'sms', 'SMS'
    #: Pela conta Twilio **da própria clínica** (`WhatsAppTwilio`), só com
    #: modelo aprovado pela Meta. Ver `docs/governance/whatsapp-twilio.md`.
    WHATSAPP = 'whatsapp', 'WhatsApp'


class DeliveryStatus(models.TextChoices):
    PENDING = 'pending', 'Na fila'
    #: Um processo tomou esta entrega e está falando com o provedor.
    #:
    #: É a posse do envio (auditoria de 2026-10-09, ND-1121-016). A chave
    #: única da entrega impedia duas **linhas**, não dois **envios**: dois
    #: consumidores do mesmo evento achavam a mesma entrega "na fila" e os
    #: dois mandavam. Passar de `pending` a `sending` é um `UPDATE`
    #: condicional, e só um ganha. Entrega que fique aqui é a de um
    #: processo morto no meio do envio -- o desfecho é desconhecido, e a
    #: tela mostra isso em vez de reenviar às cegas.
    SENDING = 'sending', 'Enviando'
    ACCEPTED = 'accepted', 'Aceita pelo provedor'
    DELIVERED = 'delivered', 'Entregue'
    UNKNOWN = 'unknown', 'Sem confirmação'
    FAILED = 'failed', 'Falhou'
    NO_CONTACT = 'no_contact', 'Sem contato cadastrado'
    #: O canal nao pode enviar: sem credencial, desligado nas
    #: configuracoes da clinica, ou organizacao inativa.
    #:
    #: Existe porque os tres casos acima vinham sendo gravados como
    #: `no_contact`, e "Sem contato cadastrado" **manda procurar no lugar
    #: errado**: quem le vai conferir o telefone do paciente, que esta
    #: certo. Foi o que aconteceu em 06/10/2026 -- um SMS recusado por
    #: falta de credencial no processo web apareceu na lista como
    #: paciente sem telefone.
    CHANNEL_UNAVAILABLE = 'channel_unavailable', 'Canal indisponível'
    NEEDS_RECONCILIATION = 'needs_reconciliation', 'Aguardando reconciliação'


class DeliveryAttemptOutcome(models.TextChoices):
    ACCEPTED = 'accepted', 'Aceita pelo provedor'
    DELIVERED = 'delivered', 'Entregue'
    UNKNOWN = 'unknown', 'Sem confirmação'
    FAILED = 'failed', 'Falhou'


class Delivery(TenantModel):
    document = models.ForeignKey(
        'documents.MedicalDocument', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    #: O terceiro alvo possível de uma entrega: o aviso de retorno previsto.
    #:
    #: Entrou como coluna própria, e não pendurado no `appointment`, porque
    #: no momento do aviso **não existe agendamento** -- é justamente disso
    #: que o e-mail trata. Reaproveitar o campo do agendamento obrigaria a
    #: criar um agendamento falso só para ter onde apontar, e ele apareceria
    #: na grade do médico.
    scheduled_return = models.ForeignKey(
        'scheduling.ScheduledReturn', on_delete=models.PROTECT, null=True, blank=True,
        related_name='deliveries',
    )
    #: O quarto alvo (1.30): o lembrete do exame marcado numa agenda de
    #: recurso. Coluna própria pelo mesmo motivo do retorno previsto: o
    #: exame não é um `Appointment`, e apontar para um falso o poria na
    #: grade de um médico.
    reserva_exame = models.ForeignKey(
        'agenda_exames.Reserva', on_delete=models.PROTECT, null=True, blank=True,
        related_name='deliveries',
    )
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='deliveries')
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    event_version = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    provider_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=100)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='communications_delivery_idem_uniq'),
            # Exatamente **um** alvo, e não "pelo menos um": uma entrega que
            # apontasse para documento e agendamento ao mesmo tempo deixaria
            # a tela de entregas dizendo duas coisas diferentes sobre a
            # mesma mensagem. Com o aviso de retorno são três colunas, e a
            # condição continua sendo a mesma pergunta -- escrita por
            # extenso porque um `sum(...) == 1` não existe em SQL de
            # restrição.
            models.CheckConstraint(
                condition=(
                    Q(document__isnull=False, appointment__isnull=True, scheduled_return__isnull=True,
                      reserva_exame__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=False, scheduled_return__isnull=True,
                        reserva_exame__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=True, scheduled_return__isnull=False,
                        reserva_exame__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=True, scheduled_return__isnull=True,
                        reserva_exame__isnull=False)
                ),
                name='communications_delivery_single_target',
            ),
        ]

    def __str__(self):
        return f'{self.channel}:{self.contact_id} ({self.status})'


class DeliveryAttempt(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name='attempts')
    attempt_number = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=DeliveryAttemptOutcome.choices)
    provider_code = models.CharField(max_length=100, blank=True)
    sanitized_error = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['delivery', 'attempt_number'], name='communications_deliveryattempt_unique',
            ),
        ]

    def __str__(self):
        return f'{self.delivery_id}#{self.attempt_number} ({self.outcome})'


class DocumentAccessToken(TenantModel):
    document = models.ForeignKey('documents.MedicalDocument', on_delete=models.PROTECT, related_name='access_tokens')
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='+')
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True)
    otp_hash = models.CharField(max_length=255, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['token_hash'], name='communications_accesstoken_hash_uniq'),
        ]

    def __str__(self):
        return f'token for document {self.document_id}'


class MessagingSettings(TenantModel):
    """Configuração de SMS da clínica, informada pelo gestor.

    A chave do provedor fica **no banco e cifrada** (`base.crypto`), não em
    variável de ambiente: quem a tem é o gestor da clínica, que a informa
    pela tela, e cada clínica tem a sua. Em texto claro, um dump do banco
    entregaria a chave de SMS de todas elas.

    `enabled` é um segundo interruptor, por clínica, além do
    `settings.SMS_ENABLED` global: a instalação pode ter o canal disponível
    e uma clínica específica preferir não usar.
    """

    provider = models.CharField(max_length=20, default='smsdev')
    sms_enabled = models.BooleanField(default=False)
    sms_api_key_ciphertext = models.TextField(blank=True)
    sms_api_key_metadata = models.JSONField(default=dict, blank=True)
    #: Só os últimos caracteres, para a tela mostrar que existe uma chave e
    #: permitir conferir que é a certa, sem exibi-la.
    sms_api_key_hint = models.CharField(max_length=40, blank=True)
    sms_sender_name = models.CharField(max_length=40, blank=True)

    # ---------------------------------------------------------------- SMTP
    #
    # Servidor de e-mail **da clínica**, e não de um médico.
    #
    # Só existia o remetente por médico (`DoctorEmailSettings`), o que
    # resolve "o e-mail sai no nome de quem atendeu" e não resolve o caso
    # mais comum: a clínica tem uma conta de e-mail, e todo mundo manda por
    # ela. Sem isto, cadastrar o SMTP era repetir servidor, porta, usuário e
    # senha em cada médico — e trocar a senha significava editar todos.
    #
    # A ordem de escolha do remetente fica: configuração do médico, se ele
    # tiver uma ativa; senão a da clínica; senão a da instalação.
    email_enabled = models.BooleanField(default=False)
    email_from_name = models.CharField(max_length=120, blank=True)
    email_from_address = models.EmailField(max_length=254, blank=True)
    email_reply_to = models.EmailField(max_length=254, blank=True)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(null=True, blank=True)
    smtp_user = models.CharField(max_length=255, blank=True)
    smtp_password_ciphertext = models.TextField(blank=True)
    smtp_password_metadata = models.JSONField(default=dict, blank=True)
    smtp_password_hint = models.CharField(max_length=40, blank=True)
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)

    # ------------------------------------------------------------ WhatsApp
    #
    # O texto que a recepção manda pelo WhatsApp da própria clínica (1.39,
    # `communications/whatsapp.py`). Não é canal de entrega: o NeuroDoc não
    # envia nada, só abre a conversa com a mensagem escrita, e quem aperta
    # "enviar" é a pessoa. Por isso não há chave, plano nem fila aqui.
    # Vazio é o texto padrão do sistema, e não "sem mensagem".
    whatsapp_texto = models.TextField(blank=True, default='')

    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='communications_messagingsettings_tenant_uniq'),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.smtp_use_tls and self.smtp_use_ssl:
            raise ValidationError({
                'smtp_use_ssl': 'TLS e SSL são alternativos: escolha um. '
                                'A porta 587 costuma usar TLS; a 465, SSL.',
            })
        if self.email_enabled and not self.email_from_address:
            raise ValidationError({'email_from_address': 'Informe o e-mail remetente da clínica.'})
        if self.email_enabled and self.smtp_host and not self.smtp_port:
            raise ValidationError({'smtp_port': 'Informe a porta do servidor SMTP.'})

    @property
    def has_api_key(self):
        return bool(self.sms_api_key_ciphertext)

    @property
    def has_smtp_password(self):
        return bool(self.smtp_password_ciphertext)

    @property
    def uses_own_smtp(self):
        return bool(self.smtp_host)

    def smtp_password(self):
        from base.crypto import decrypt_secret

        return decrypt_secret(self.smtp_password_ciphertext, self.smtp_password_metadata)

    def sender_header(self):
        if self.email_from_name and self.email_from_address:
            return _remetente(self.email_from_name, self.email_from_address)
        return self.email_from_address

    def api_key(self):
        """Chave em claro, para a chamada ao provedor.

        Levanta `SecretUnavailable` quando não abre — e é isso que se quer:
        tratar como vazio faria o sistema chamar o SMSDEV com chave em
        branco e reportar erro do provedor em vez do erro real.
        """
        from base.crypto import decrypt_secret

        return decrypt_secret(self.sms_api_key_ciphertext, self.sms_api_key_metadata)

    def __str__(self):
        return f'SMS {self.provider} ({"ativo" if self.sms_enabled else "inativo"})'


class DoctorEmailSettings(TenantModel):
    """Remetente de e-mail de um médico, configurado pelo gestor.

    Por médico porque o e-mail que o paciente recebe deve vir do consultório
    de quem o atende — e numa clínica com vários médicos isso são vários
    remetentes. Sem configuração própria, o envio usa o remetente global da
    instalação.

    A senha do SMTP fica cifrada, pelo mesmo motivo da chave do SMS.
    """

    physician_membership = models.OneToOneField(
        'tenancy.Membership', on_delete=models.CASCADE, related_name='email_settings',
    )
    enabled = models.BooleanField(default=False)
    from_name = models.CharField(max_length=120, blank=True)
    from_email = models.EmailField(max_length=254, blank=True)
    reply_to = models.EmailField(max_length=254, blank=True)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(null=True, blank=True)
    smtp_user = models.CharField(max_length=255, blank=True)
    smtp_password_ciphertext = models.TextField(blank=True)
    smtp_password_metadata = models.JSONField(default=dict, blank=True)
    smtp_password_hint = models.CharField(max_length=40, blank=True)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        pass

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.use_tls and self.use_ssl:
            raise ValidationError({
                'use_ssl': 'TLS e SSL são alternativos: escolha um. '
                           'A porta 587 costuma usar TLS; a 465, SSL.',
            })
        if self.enabled and not self.from_email:
            raise ValidationError({'from_email': 'Informe o e-mail remetente.'})
        if self.enabled and self.smtp_host and not self.smtp_port:
            raise ValidationError({'smtp_port': 'Informe a porta do servidor SMTP.'})

    @property
    def has_password(self):
        return bool(self.smtp_password_ciphertext)

    @property
    def uses_own_server(self):
        """Se tem servidor próprio, ou só troca o endereço do remetente.

        As duas coisas são úteis: um médico pode querer só que o e-mail saia
        no nome dele, usando o servidor da instalação.
        """
        return bool(self.smtp_host)

    def smtp_password(self):
        from base.crypto import decrypt_secret

        return decrypt_secret(self.smtp_password_ciphertext, self.smtp_password_metadata)

    def sender_header(self):
        if self.from_name and self.from_email:
            return _remetente(self.from_name, self.from_email)
        return self.from_email

    def __str__(self):
        return f'e-mail de {self.physician_membership_id} ({self.from_email or "sem remetente"})'


class CampaignStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    SENDING = 'sending', 'Enviando'
    PAUSED = 'paused', 'Pausada'
    SENT = 'sent', 'Concluída'
    CANCELLED = 'cancelled', 'Cancelada'


class MarketingCampaign(TenantModel):
    """Comunicação em massa da clínica, com registro do que saiu.

    Existe sob restrições que não são detalhe de implementação:

    - **Só vai para quem consentiu.** A lista de destinatários é congelada
      na criação a partir dos contatos com `marketing_opt_in_at`, e o
      consentimento é reconferido no instante do envio — alguém que se
      descadastrou entre a criação e o disparo não recebe.
    - **Toda mensagem leva link de descadastro.** Não é opção da tela: é
      acrescentado no envio, e uma campanha sem ele não sai.
    - **Ritmo controlado.** `per_minute` limita quantos e-mails saem por
      minuto, para não derrubar o servidor SMTP nem queimar a reputação do
      domínio — provedor que recebe mil mensagens de uma vez de um
      remetente novo trata as próximas como spam.

    O que **não** se mede aqui é abertura. Pixel de rastreamento numa
    mensagem a paciente registraria quando e de onde ele leu, o que é
    vigilância sobre dado de saúde para responder a uma pergunta de
    marketing. A taxa medida é a de **entrega** — o que o servidor aceitou
    e o que ele recusou —, que é o que responde "a mensagem saiu?".
    """

    subject = models.CharField(max_length=200)
    #: O texto simples. Opcional quando há HTML: a parte `text/plain` sai
    #: então do próprio HTML (`email_html.texto_do_html`). Uma das duas é
    #: obrigatória, conferido no formulário e na guarda do disparo.
    body_text = models.TextField(blank=True)
    #: O corpo em HTML com CSS (2026-11-22), já limpo ao gravar e limpo de
    #: novo ao enviar (`email_html.limpar_html`). Vazio = a campanha sai
    #: só em texto, como antes.
    body_html = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT)
    #: Mensagens por minuto. O padrão é conservador de propósito: é mais
    #: fácil aumentar depois de ver o servidor aguentando do que recuperar
    #: um domínio marcado como spam.
    per_minute = models.PositiveSmallIntegerField(default=20)
    created_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'status'], name='comm_campaign_status_idx'),
        ]

    @property
    def counts(self):
        rows = self.recipients.values_list('status', flat=True)
        total = 0
        by_status = {}
        for value in rows:
            total += 1
            by_status[value] = by_status.get(value, 0) + 1
        return {'total': total, **by_status}

    @property
    def delivery_rate(self):
        """Proporção aceita pelo servidor, entre as já processadas.

        Divide pelo que foi tentado, e não pelo total: uma campanha no meio
        do envio mostraria taxa caindo à medida que avança, o que faria o
        número parecer um problema quando é só progresso.
        """
        counts = self.counts
        enviadas = counts.get(RecipientStatus.SENT, 0)
        falhas = counts.get(RecipientStatus.FAILED, 0)
        processadas = enviadas + falhas
        if not processadas:
            return None
        return enviadas / processadas

    def __str__(self):
        return f'{self.subject} ({self.get_status_display()})'


class RecipientStatus(models.TextChoices):
    PENDING = 'pending', 'Na fila'
    SENT = 'sent', 'Aceita pelo servidor'
    FAILED = 'failed', 'Recusada'
    SKIPPED = 'skipped', 'Não enviada'


class CampaignLink(TenantModel):
    """Um link da campanha, e quantas vezes ele foi clicado (2026-11-22).

    **O mesmo link para todos os destinatários, de propósito.** O endereço
    `/c/<token>/` não carrega quem recebeu: o clique soma no link, e não
    num paciente. É a medida que a campanha pode ter sem virar vigilância
    sobre dado de saúde — "o link da agenda teve 42 cliques" responde se a
    campanha funcionou; "o paciente X clicou" não muda nada no cuidado dele
    e criaria um registro por pessoa (ver o docstring da campanha, que
    recusa o pixel de abertura pelo mesmo motivo). Nem IP nem navegador
    são guardados.

    Apagado junto com a campanha: o link no e-mail já entregue passa a
    responder que não está mais disponível.
    """

    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.CASCADE, related_name='links')
    url = models.URLField(max_length=2000)
    token = models.CharField(max_length=32, unique=True)
    clicks = models.PositiveIntegerField(default=0)
    last_click_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['campaign', 'url'], name='comm_campaign_link_url_uniq'),
        ]

    def __str__(self):
        return f'{self.url} ({self.clicks})'


class MarketingRecipient(TenantModel):
    """Um destinatário de uma campanha, com o que aconteceu com ele.

    Uma linha por contato, criada quando a campanha é montada. É o que
    permite responder depois "esta pessoa recebeu?" sem depender de log do
    servidor de e-mail, e é o que impede o reenvio de duplicar mensagem:
    quem já está `sent` não é processado de novo.
    """

    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.CASCADE, related_name='recipients')
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='+')
    #: Cópia do endereço no momento do envio. O contato pode mudar de
    #: e-mail depois, e o registro tem de dizer para onde a mensagem foi de
    #: fato — não para onde iria hoje.
    email = models.EmailField(max_length=254)
    status = models.CharField(max_length=20, choices=RecipientStatus.choices, default=RecipientStatus.PENDING)
    sent_at = models.DateTimeField(null=True, blank=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['campaign', 'contact'], name='comm_marketingrecipient_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['campaign', 'status'], name='comm_recipient_status_idx'),
        ]

    def __str__(self):
        return f'{self.email} ({self.status})'


class WhatsAppTwilio(TenantModel):
    """A conta Twilio **da clínica** para o WhatsApp automático (BYO).

    Uma linha por clínica. A clínica contrata e paga a Twilio e a Meta; o
    sistema guarda só as credenciais dela, cifradas, e chama a API em nome
    dela. Decisões em `docs/governance/whatsapp-twilio.md`.

    **Preencher não é funcionar.** `verificado_em` só é gravado pela
    verificação feita no worker contra a Twilio, e qualquer troca de
    credencial ou de número o apaga (`invalidar_verificacao`): a tela volta a
    "Pendente" e o envio para até verificar de novo. Sem isso, um token
    digitado errado apareceria como canal pronto até o primeiro paciente
    ficar sem aviso.
    """

    account_sid = models.CharField(max_length=40, blank=True)
    #: O Auth Token **principal**: é ele que assina os avisos de status
    #: (`X-Twilio-Signature`), e sem conferir a assinatura o aviso não pode
    #: ser aceito. Envelope de `base.crypto`, como a chave do SMS.
    auth_token_ciphertext = models.TextField(blank=True)
    auth_token_metadata = models.JSONField(default=dict, blank=True)
    auth_token_hint = models.CharField(max_length=40, blank=True)
    #: O número do WhatsApp da clínica, em E.164 (`+5511999998888`).
    numero = models.CharField(max_length=20, blank=True)
    #: Opcional. Com ele, o envio vai por `MessagingServiceSid` em vez de
    #: `From`: a documentação da Twilio é ambígua sobre exigir o serviço no
    #: envio de modelo, e o campo cobre as contas em que ele é exigido.
    messaging_service_sid = models.CharField(max_length=40, blank=True)

    #: O interruptor da clínica: suspender e reativar sem apagar nada.
    ativo = models.BooleanField(default=False)

    #: A última verificação contra a Twilio. `verificado_em` só com sucesso;
    #: a falha deixa o código e a explicação, sem segredo nem dado pessoal.
    verificacao_pedida_em = models.DateTimeField(null=True, blank=True)
    verificacao_concluida_em = models.DateTimeField(null=True, blank=True)
    verificado_em = models.DateTimeField(null=True, blank=True)
    conta_tipo = models.CharField(max_length=20, blank=True)
    remetente_status = models.CharField(max_length=40, blank=True)
    remetente_qualidade = models.CharField(max_length=40, blank=True)
    remetente_limite = models.CharField(max_length=60, blank=True)
    erro_codigo = models.CharField(max_length=20, blank=True)
    erro_texto = models.CharField(max_length=300, blank=True)

    #: Parte aleatória da URL do aviso de status. **Só acha a clínica**; quem
    #: autentica é a assinatura da Twilio. Não é o id da clínica de
    #: propósito: o aviso chega de fora, e um id adivinhável seria convite.
    token_webhook = models.CharField(max_length=64, unique=True)

    #: O envio de teste (para o celular de quem configura), e a situação que
    #: o aviso da Twilio devolveu para ele. O número do teste não é guardado.
    teste_enviado_em = models.DateTimeField(null=True, blank=True)
    teste_sid = models.CharField(max_length=64, blank=True)
    teste_status = models.CharField(max_length=40, blank=True)
    teste_erro = models.CharField(max_length=300, blank=True)

    updated_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='comm_whatsapp_twilio_tenant_uniq'),
        ]

    @property
    def tem_token(self):
        return bool(self.auth_token_ciphertext)

    @property
    def tem_credenciais(self):
        return bool(self.account_sid and self.auth_token_ciphertext and self.numero)

    def auth_token(self):
        from base.crypto import decrypt_secret

        if not self.auth_token_ciphertext:
            return ''
        return decrypt_secret(self.auth_token_ciphertext, self.auth_token_metadata)

    def invalidar_verificacao(self):
        """Volta a "Pendente": credencial ou número mudou desde a verificação."""
        self.verificado_em = None
        self.verificacao_concluida_em = None
        self.remetente_status = ''
        self.remetente_qualidade = ''
        self.remetente_limite = ''
        self.conta_tipo = ''
        self.erro_codigo = ''
        self.erro_texto = ''

    def __str__(self):
        return f'WhatsApp Twilio de {self.tenant_id}'


class WhatsAppModelo(TenantModel):
    """O modelo aprovado pela Meta que a clínica usa numa ocasião.

    Fora da janela de 24 h o WhatsApp só entrega modelo aprovado (erro 63016),
    e todo aviso deste sistema é iniciado pela clínica — por isso não há envio
    de texto livre. O texto mora na Twilio (Content Template Builder); aqui
    fica só o identificador (`HX…`) e o que a verificação conferiu nele.
    """

    evento = models.CharField(max_length=20)
    content_sid = models.CharField(max_length=40, blank=True)
    #: A clínica escolhe em que ocasiões o WhatsApp é usado.
    ligado = models.BooleanField(default=False)
    aprovacao = models.CharField(max_length=30, blank=True)
    variaveis = models.PositiveSmallIntegerField(null=True, blank=True)
    idioma = models.CharField(max_length=10, blank=True)
    nome_na_twilio = models.CharField(max_length=200, blank=True)
    conferido_em = models.DateTimeField(null=True, blank=True)
    erro_texto = models.CharField(max_length=300, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'evento'], name='comm_whatsapp_modelo_uniq'),
        ]

    def __str__(self):
        return f'{self.evento}: {self.content_sid or "sem modelo"}'
