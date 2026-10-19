from django.db import models
from django.db.models import Q

from base.models import TenantModel

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_PAGES = 100
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'docx'}


class AttachmentClassification(models.TextChoices):
    CLINICAL = 'clinical', 'Clínico'
    ADMINISTRATIVE = 'administrative', 'Administrativo'


class AttachmentScanStatus(models.TextChoices):
    QUARANTINED = 'quarantined', 'Em quarentena'
    AVAILABLE = 'available', 'Liberado'
    REJECTED = 'rejected', 'Recusado'


class Attachment(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='attachments')
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.SET_NULL, null=True, blank=True, related_name='attachments',
    )
    storage_key = models.CharField(max_length=512, blank=True)
    original_name = models.CharField(max_length=255)
    mime = models.CharField(max_length=100)
    bytes = models.PositiveBigIntegerField()
    page_count = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64)
    classification = models.CharField(max_length=40, choices=AttachmentClassification.choices)
    scan_status = models.CharField(
        max_length=40, choices=AttachmentScanStatus.choices, default=AttachmentScanStatus.QUARANTINED,
    )
    scan_error = models.CharField(max_length=255, blank=True)
    #: Quem enviou. Nulo só quando quem enviou não tem conta: o paciente,
    #: pelo portal (`PortalExamUpload` diz quem preencheu). Era obrigatório,
    #: e obrigar aqui faria o portal inventar um usuário dono do arquivo --
    #: o que poria na trilha um médico que nunca tocou nele.
    uploaded_by = models.ForeignKey(
        'accounts.User', on_delete=models.PROTECT, related_name='+', null=True, blank=True,
    )
    document_date = models.DateField(null=True, blank=True)
    encryption_metadata = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient'], name='documents_attach_patient_idx'),
        ]

    def __str__(self):
        return f'{self.original_name} ({self.scan_status})'


class AttachmentOcrPage(TenantModel):
    attachment = models.ForeignKey(Attachment, on_delete=models.PROTECT, related_name='ocr_pages')
    page_number = models.PositiveIntegerField()
    text = models.TextField(max_length=50000, blank=True)
    engine = models.CharField(max_length=40, default='tesseract')

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['attachment', 'page_number'], name='documents_ocrpage_unique_page'),
        ]

    def __str__(self):
        return f'{self.attachment_id} p{self.page_number}'


class MedicalDocumentKind(models.TextChoices):
    PRESCRIPTION = 'prescription', 'Receita'
    REPORT = 'report', 'Relatório'
    REQUEST = 'request', 'Pedido de exame'
    REFERRAL = 'referral', 'Encaminhamento'


class MedicalDocumentStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    READY_TO_SIGN = 'ready_to_sign', 'Pronto para assinar'
    SIGNING = 'signing', 'Assinando'
    ISSUED = 'issued', 'Emitido'
    #: Emitido para ser assinado à mão e carimbado no papel.
    #:
    #: Existe porque a alternativa era imprimir o rascunho — e o rascunho
    #: sai com "RASCUNHO SEM VALIDADE" em vermelho no rodapé. Entregar ao
    #: paciente uma receita que declara não valer é pior do que não ter a
    #: funcionalidade.
    #:
    #: Tem número, tem data e **não tem QR**: o QR leva à página que afirma
    #: que o documento saiu deste sistema e não foi alterado, e isso quem
    #: sustenta é a assinatura digital. Num papel assinado à caneta, o que
    #: responde por ele é a assinatura e o carimbo.
    ISSUED_ON_PAPER = 'issued_on_paper', 'Emitido para assinatura física'
    FAILED = 'failed', 'Falhou'


class MedicalDocument(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='medical_documents')
    #: O atendimento a que o documento pertence, quando há um.
    #:
    #: Opcional porque a renovação de receita sem consulta é o pedido real
    #: do balcão — o paciente liga, o médico emite, e não houve
    #: atendimento. Exigir um atendimento aqui obrigava a abrir uma
    #: consulta falsa só para poder imprimir, e uma consulta que não houve
    #: no prontuário é pior do que um documento sem consulta.
    #:
    #: O paciente continua obrigatório: documento sem paciente não existe.
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, related_name='medical_documents',
        null=True, blank=True,
    )
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='medical_documents',
    )
    document_number = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)
    kind = models.CharField(max_length=40, choices=MedicalDocumentKind.choices)
    template_version = models.CharField(max_length=20, default='v1')
    content_snapshot = models.JSONField(default=dict, blank=True)
    pdf_attachment = models.ForeignKey(
        Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    signed_pdf_attachment = models.ForeignKey(
        Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    status = models.CharField(max_length=40, choices=MedicalDocumentStatus.choices, default=MedicalDocumentStatus.DRAFT)
    issued_at = models.DateTimeField(null=True, blank=True)
    signature_metadata = models.JSONField(default=dict, blank=True)
    #: Código do QR e da página pública de verificação.
    #:
    #: Aleatório, e não derivado do id nem do número do documento: quem
    #: recebe uma receita não pode, a partir dela, adivinhar o código da
    #: receita seguinte e conferir o documento de outro paciente. Um
    #: contador sequencial no QR seria exatamente isso.
    #:
    #: Nasce junto com o rascunho porque o QR é desenhado dentro do PDF, e
    #: o PDF final é montado antes de ser assinado — assinar depois de
    #: acrescentar qualquer coisa invalidaria a assinatura.
    validation_token = models.CharField(max_length=64, blank=True, db_index=True)
    replaces_document = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replaced_by',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'document_number'], condition=~Q(document_number=''),
                name='documents_medicaldocument_number_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'patient'], name='documents_meddoc_patient_idx'),
        ]

    def __str__(self):
        return self.document_number or f'{self.kind} draft ({self.id})'


class SigningCredentialStatus(models.TextChoices):
    ACTIVE = 'active', 'Ativo'
    EXPIRED = 'expired', 'Expirado'
    REVOKED = 'revoked', 'Revogado'


class SigningCredential(TenantModel):
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='signing_credentials',
    )
    ciphertext_path = models.CharField(max_length=512)
    wrapped_key_metadata = models.JSONField(default=dict)
    certificate_serial = models.CharField(max_length=64)
    certificate_fingerprint = models.CharField(max_length=64)
    issuer = models.CharField(max_length=255)
    not_before = models.DateTimeField()
    not_after = models.DateTimeField()
    status = models.CharField(
        max_length=40, choices=SigningCredentialStatus.choices, default=SigningCredentialStatus.ACTIVE,
    )

    def __str__(self):
        return f'{self.certificate_serial} ({self.status})'


class SigningSession(TenantModel):
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='signing_sessions',
    )
    credential = models.ForeignKey(SigningCredential, on_delete=models.PROTECT, related_name='sessions')
    duration_hours = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    mfa_at = models.DateTimeField()
    session_binding_hash = models.CharField(max_length=64)
    encrypted_unlock_material = models.TextField()
    ephemeral_key_id = models.UUIDField()

    def __str__(self):
        return f'session {self.id} ({self.physician_id})'


class DocumentRequestKind(models.TextChoices):
    PRESCRIPTION_SIMPLE = 'prescription_simple', 'Receita simples'
    PRESCRIPTION_SPECIAL = 'prescription_special', 'Receita de controle especial'
    REPORT = 'report', 'Relatório médico'
    EXAMS = 'exams', 'Pedido de exames'


class DocumentRequestStatus(models.TextChoices):
    RECEIVED = 'received', 'Recebida'
    IN_REVIEW = 'in_review', 'Em revisão'
    FULFILLED = 'fulfilled', 'Atendida'
    DECLINED = 'declined', 'Recusada'


class DocumentRequest(TenantModel):
    """Pedido feito pelo paciente no portal público.

    É **pedido**, não documento. Nada aqui vale como receita, laudo ou
    encaminhamento: o paciente descreve o que precisa, e o médico decide o
    que emitir — inclusive não emitir. A distinção não é formalidade; um
    sistema em que o paciente escreve a própria prescrição e o sistema a
    imprime não é um prontuário.

    O conteúdo fica em `payload` porque cada tipo pede coisas diferentes —
    lista de medicações, finalidade do relatório, exames — e colunas
    separadas para cada uma deixariam a tabela com metade dos campos
    sempre vazios.

    O consentimento de tratamento dos dados é registrado no ato: quem
    preencheu confirmou, quando, e sob qual versão do aviso.
    """

    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='document_requests')
    kind = models.CharField(max_length=40, choices=DocumentRequestKind.choices)
    #: Quem preencheu. O paciente costuma ser, mas filho e cuidador também
    #: pedem — e saber quem pediu importa quando o conteúdo estranha.
    requester_name = models.CharField(max_length=255)
    requester_is_patient = models.BooleanField(default=True)
    payload = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20, choices=DocumentRequestStatus.choices, default=DocumentRequestStatus.RECEIVED,
    )
    reviewed_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)
    #: O documento que nasceu deste pedido, quando nasceu.
    resulting_document = models.ForeignKey(
        MedicalDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    privacy_ack_at = models.DateTimeField(null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20, blank=True)
    #: IP protegido, como no resto do sistema — nunca em texto claro.
    origin_ip_protected = models.CharField(max_length=64, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'status'], name='documents_request_status_idx'),
        ]

    @property
    def is_open(self):
        return self.status in (DocumentRequestStatus.RECEIVED, DocumentRequestStatus.IN_REVIEW)

    def __str__(self):
        return f'{self.get_kind_display()} — {self.patient_id} ({self.status})'


class PortalExamType(models.TextChoices):
    """O que o paciente diz que o exame é.

    Lista fechada, com "Outro" e o nome escrito à mão: em texto livre o
    mesmo exame chega como "RM", "ressonancia" e "Ressonância do crânio", e
    o médico que procura "a ressonância que ele mandou" não acha pela lista.
    A ordem é a da frequência numa clínica de neurologia, não a alfabética.
    """

    RESSONANCIA = 'ressonancia', 'Ressonância magnética'
    TOMOGRAFIA = 'tomografia', 'Tomografia computadorizada'
    ELETRONEUROMIOGRAFIA = 'eletroneuromiografia', 'Eletroneuromiografia'
    ELETROENCEFALOGRAMA = 'eletroencefalograma', 'Eletroencefalograma'
    LABORATORIAL = 'laboratorial', 'Exames laboratoriais (sangue, urina)'
    LIQUOR = 'liquor', 'Líquor'
    DOPPLER = 'doppler', 'Doppler / ultrassonografia'
    POLISSONOGRAFIA = 'polissonografia', 'Polissonografia'
    POTENCIAL_EVOCADO = 'potencial_evocado', 'Potencial evocado'
    NEUROPSICOLOGICA = 'neuropsicologica', 'Avaliação neuropsicológica'
    RAIO_X = 'raio_x', 'Raio-X'
    OUTRO = 'outro', 'Outro'


class PortalExamUpload(TenantModel):
    """Laudo de exame que o próprio paciente enviou pelo portal.

    O arquivo é um `Attachment` como qualquer outro -- mesma quarentena,
    mesmo antivírus, mesma guarda de vinte anos, mesma regra de quem abre --
    e entra direto no prontuário, sem fila de aprovação: é resultado de
    exame que o paciente já tem na mão, não pedido de ato médico.

    O que esta linha acrescenta ao anexo é o que só o paciente sabe dizer
    (qual exame, quando, onde) e o **ciente** do médico: o envio fica
    marcado como novo no prontuário até alguém com acesso clínico dizer
    que viu. Sem isso o laudo entraria calado numa lista que ninguém abre
    sem motivo.
    """

    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, related_name='exames_do_portal',
    )
    attachment = models.OneToOneField(
        Attachment, on_delete=models.PROTECT, related_name='envio_portal',
    )
    exam_type = models.CharField(max_length=40, choices=PortalExamType.choices)
    #: O nome do exame quando o tipo é "Outro". Vazio nos demais.
    exam_other = models.CharField(max_length=120, blank=True)
    performed_on = models.DateField()
    #: Laboratório, clínica ou profissional que fez o exame.
    performed_at_place = models.CharField(max_length=160)
    #: Nome do arquivo como chegou. O anexo grava um nome gerado (tipo e
    #: data), porque o do paciente costuma ter acento, espaço duplo e
    #: parêntese, que o validador de nome recusa; este fica só de registro.
    original_filename = models.CharField(max_length=255, blank=True)

    requester_name = models.CharField(max_length=255)
    requester_is_patient = models.BooleanField(default=True)
    privacy_ack_at = models.DateTimeField(null=True, blank=True)
    privacy_notice_version = models.CharField(max_length=20, blank=True)
    origin_ip_protected = models.CharField(max_length=64, blank=True)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(
                fields=['tenant', 'patient', 'acknowledged_at'],
                name='documents_portalexam_pend_idx',
            ),
        ]

    @property
    def exam_label(self):
        if self.exam_type == PortalExamType.OUTRO and self.exam_other:
            return self.exam_other
        return self.get_exam_type_display()

    def __str__(self):
        return f'{self.exam_label} — {self.patient_id} ({self.performed_on})'
