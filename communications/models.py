from django.db import models
from django.db.models import Q

from base.models import TenantModel


class DeliveryChannel(models.TextChoices):
    EMAIL = 'email', 'E-mail'
    SMS = 'sms', 'SMS'


class DeliveryStatus(models.TextChoices):
    PENDING = 'pending', 'Na fila'
    ACCEPTED = 'accepted', 'Aceita pelo provedor'
    DELIVERED = 'delivered', 'Entregue'
    UNKNOWN = 'unknown', 'Sem confirmação'
    FAILED = 'failed', 'Falhou'
    NO_CONTACT = 'no_contact', 'Sem contato cadastrado'
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
            models.CheckConstraint(
                condition=(
                    Q(document__isnull=False, appointment__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=False)
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
            return f'{self.email_from_name} <{self.email_from_address}>'
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
            return f'{self.from_name} <{self.from_email}>'
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
    body_text = models.TextField()
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
