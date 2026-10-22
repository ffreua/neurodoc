from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from base.models import TenantModel
from base.validators import is_valid_cpf


class SexAtRegistration(models.TextChoices):
    FEMALE = 'female', 'Feminino'
    MALE = 'male', 'Masculino'
    INTERSEX = 'intersex', 'Intersexo'
    NOT_INFORMED = 'not_informed', 'Não informado'


class MaritalStatus(models.TextChoices):
    SINGLE = 'single', 'Solteiro(a)'
    MARRIED = 'married', 'Casado(a)'
    STABLE_UNION = 'stable_union', 'União estável'
    DIVORCED = 'divorced', 'Divorciado(a)'
    WIDOWED = 'widowed', 'Viúvo(a)'
    OTHER = 'other', 'Outro'
    NOT_INFORMED = 'not_informed', 'Não informado'


class ReferralSource(models.TextChoices):
    PATIENT = 'patient', 'Paciente'
    PHYSICIAN = 'physician', 'Médico'
    INTERNET = 'internet', 'Internet'
    PLAN = 'plan', 'Plano'
    OTHER = 'other', 'Outro'
    NOT_INFORMED = 'not_informed', 'Não informado'


class PaymentCategory(models.TextChoices):
    PRIVATE = 'private', 'Particular'
    PLAN = 'plan', 'Plano'


class PatientStatus(models.TextChoices):
    ACTIVE = 'active', 'Ativo'
    ARCHIVED = 'archived', 'Arquivado'


class RegistrationStage(models.TextChoices):
    """Quão completo está o cadastro.

    `preliminary` existe para o agendamento por telefone: a secretaria tem
    nome e telefone, e é com isso que precisa marcar o horário. Exigir CPF,
    endereço e forma de pagamento naquele momento significa ou perder o
    agendamento ou inventar dados para passar da tela.

    O cadastro é completado quando o paciente chega — é no check-in que a
    ficha inteira aparece para ser preenchida.
    """

    PRELIMINARY = 'preliminary', 'Pré-cadastro'
    COMPLETE = 'complete', 'Cadastro completo'


class Insurer(TenantModel):
    name = models.CharField(max_length=255)
    ans_registration = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class HealthPlanKind(models.TextChoices):
    AMBULATORIAL = 'ambulatorial', 'Ambulatorial'
    HOSPITALAR = 'hospitalar', 'Hospitalar'
    HOSPITALAR_OBSTETRICIA = 'hospitalar_obstetricia', 'Hospitalar com obstetrícia'
    REFERENCIA = 'referencia', 'Referência'
    ODONTOLOGICO = 'odontologico', 'Odontológico'
    OTHER = 'other', 'Outro'
    NOT_INFORMED = 'not_informed', 'Não informado'


class HealthPlan(TenantModel):
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name='plans')
    name = models.CharField(max_length=255)
    kind = models.CharField(
        max_length=40, choices=HealthPlanKind.choices, default=HealthPlanKind.NOT_INFORMED,
    )
    active = models.BooleanField(default=True)
    administrative_notes = models.TextField(max_length=2000, blank=True)


    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'insurer', 'name'], name='patients_healthplan_tenant_insurer_name_uniq'),
        ]

    def __str__(self):
        return f'{self.insurer.name} — {self.name}'


class PatientNumberSequence(TenantModel):
    """O último número de prontuário emitido por esta clínica.

    Um contador próprio, e não "o maior número em uso mais um".

    A diferença aparece quando um paciente é apagado. Derivar do maior em
    uso devolve o número do apagado ao próximo cadastro: dois prontuários
    diferentes, na história da mesma clínica, com o mesmo número — e o
    primeiro deles possivelmente já impresso em documento entregue.
    Prontuário é registro permanente; o número de um não volta a ser de
    outro.

    Também tira uma varredura do caminho: derivar do maior obrigava a ler
    o número de **todos** os pacientes da clínica a cada cadastro novo.
    """

    last_number = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant'], name='patients_numbersequence_tenant_uniq'),
        ]

    def __str__(self):
        return f'{self.tenant_id}: {self.last_number}'


class Patient(TenantModel):
    #: Número do prontuário — o identificador que se fala em voz alta.
    #:
    #: O sistema já liga tudo ao paciente por chave estrangeira, e é isso
    #: que garante que o documento de um não apareça no prontuário de
    #: outro. Este número não acrescenta isolamento nenhum: ele serve às
    #: pessoas. UUID não se dita ao telefone, não se escreve na aba de uma
    #: pasta, não se confere em voz alta com o laboratório que ligou
    #: perguntando de um exame.
    #:
    #: Sequencial por clínica, atribuído na criação e imutável depois:
    #: número de prontuário que muda deixa de servir para o que existe.
    #:
    #: **Não é credencial.** É curto e previsível por construção — quem tem
    #: o 000123 adivinha o 000124. Quem pode ver o prontuário continua
    #: sendo decidido pela matriz de permissões, nunca por conhecer o
    #: número.
    record_number = models.CharField(max_length=20, blank=True, db_index=True)
    full_name = models.CharField(max_length=255)
    birth_date = models.DateField(null=True, blank=True)
    birth_date_unknown_reason = models.CharField(max_length=255, blank=True)
    estimated_birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    sex_at_registration = models.CharField(
        max_length=40, choices=SexAtRegistration.choices, default=SexAtRegistration.NOT_INFORMED,
    )
    cpf = models.CharField(max_length=11, null=True, blank=True)
    identity_number = models.CharField(max_length=30, blank=True)
    mother_name = models.CharField(max_length=255, blank=True)

    # ----------------------------------------------------- naturalidade
    #
    # Onde a pessoa nasceu, que é coisa diferente de onde ela mora. Entra
    # no cadastro porque é dado de identificação em relatório e perícia —
    # e porque em neurologia a procedência importa clinicamente: doença
    # de Chagas, neurocisticercose e endemias regionais mudam a lista de
    # hipóteses conforme o lugar de origem.
    #
    # **Texto livre, com catálogo sugerindo.** `birth_city` é `CharField`
    # e não chave estrangeira para `catalogs.Municipality`, de propósito:
    # paciente nascido fora do Brasil não está em lista nenhuma de
    # município brasileiro, e município que muda de nome (e muda)
    # reescreveria a ficha antiga. O catálogo serve ao autocomplete; o
    # que fica gravado é o que a pessoa declarou.
    birth_country = models.CharField(max_length=2, default='BR', blank=True)
    birth_city = models.CharField(max_length=120, blank=True)
    #: Só faz sentido com `birth_country='BR'`. Vazio para quem nasceu
    #: fora — e é por isso que não é uma UF obrigatória.
    birth_state = models.CharField(max_length=2, blank=True)
    postal_code = models.CharField(max_length=8, blank=True)
    street = models.CharField(max_length=255, blank=True)
    number = models.CharField(max_length=30, blank=True)
    complement = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default='BR')
    address_source = models.CharField(max_length=40, blank=True)
    referral_source = models.CharField(
        max_length=40, choices=ReferralSource.choices, default=ReferralSource.NOT_INFORMED,
    )
    referral_details = models.CharField(max_length=255, blank=True)
    marital_status = models.CharField(
        max_length=40, choices=MaritalStatus.choices, default=MaritalStatus.NOT_INFORMED,
    )
    occupation = models.CharField(max_length=150, blank=True)
    payment_category = models.CharField(max_length=40, choices=PaymentCategory.choices, default=PaymentCategory.PRIVATE)
    active_coverage = models.ForeignKey(
        'patients.PatientCoverage', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    responsible_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='responsible_patients',
    )
    administrative_notes = models.TextField(max_length=2000, blank=True)

    #: Identificador desta ficha no sistema de onde ela foi migrada.
    #:
    #: Existe por um motivo prático e um de rastreabilidade.
    #:
    #: O prático: **importação precisa poder ser repetida.** Migrar duas
    #: mil fichas é uma operação que falha no meio — uma linha com dado
    #: impossível, uma queda de conexão — e sem uma chave estável a
    #: segunda tentativa duplicaria tudo o que a primeira já gravou.
    #: Casar por nome não serve (homônimo existe) e por CPF também não
    #: (37 fichas vieram sem).
    #:
    #: O de rastreabilidade: quando a secretária achar um dado estranho na
    #: ficha de alguém, a pergunta vai ser "veio assim do sistema antigo?",
    #: e sem este número não há como responder.
    #:
    #: Vazio para quem nasceu aqui, que é o caso de quase todo mundo daqui
    #: para frente.
    legacy_id = models.CharField(max_length=60, blank=True, db_index=True)

    # ------------------------------------------------------- fotografia
    #
    # Uma por paciente, guardada fora do banco (`patients.photo`), com o
    # caminho gravado aqui em vez de derivado do id. A extensão varia com o
    # formato enviado, e derivar o caminho obrigaria a tentar `.png`,
    # `.jpg` e `.webp` a cada leitura — três acessos ao disco para exibir
    # um retrato, e um bug calado no dia em que um quarto formato entrar.
    #
    # Não é anexo de prontuário: ver o cabeçalho de `patients/photo.py`.
    # O consentimento do paciente para a fotografia é colhido em papel,
    # fora do sistema (decisão do produto, setembro/2026); o que fica aqui
    # é quem enviou e quando, pela trilha de auditoria.
    photo_path = models.CharField(max_length=500, blank=True)
    photo_mime = models.CharField(max_length=100, blank=True)
    photo_bytes = models.PositiveIntegerField(default=0)
    photo_updated_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=40, choices=PatientStatus.choices, default=PatientStatus.ACTIVE)
    registration_stage = models.CharField(
        max_length=20, choices=RegistrationStage.choices, default=RegistrationStage.COMPLETE,
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'cpf'], name='patients_patient_tenant_cpf_uniq',
                condition=models.Q(cpf__isnull=False),
            ),
            models.UniqueConstraint(
                fields=['tenant', 'record_number'],
                name='patients_patient_tenant_record_number_uniq',
                condition=~models.Q(record_number=''),
            ),
            # Duas fichas não podem apontar para o mesmo registro do
            # sistema antigo: é isso que faz a reimportação encontrar a
            # linha que já existe em vez de criar outra.
            models.UniqueConstraint(
                fields=['tenant', 'legacy_id'],
                name='patients_patient_tenant_legacy_id_uniq',
                condition=~models.Q(legacy_id=''),
            ),
        ]
        indexes = [
            models.Index(Lower('full_name'), name='patients_patient_name_idx'),
        ]

    #: Campos de nome de pessoa que seguem a forma canônica do cadastro.
    #:
    #: O nome da mãe entra junto porque ela aparece na mesma ficha e no
    #: mesmo documento impresso que o do paciente — padronizar um e deixar
    #: o outro como veio deixaria a receita com "MARIA DA SILVA, filha de
    #: joana silva", que é pior do que não padronizar nada.
    CAMPOS_DE_NOME = ('full_name', 'mother_name')

    def _normalizar_nomes(self):
        from .naming import normalizar_nome

        for campo in self.CAMPOS_DE_NOME:
            setattr(self, campo, normalizar_nome(getattr(self, campo, '')))

    def clean(self):
        # Normaliza antes de validar para que o formulário, ao redesenhar
        # com erro em outro campo, já mostre o nome como ele vai ficar
        # gravado — em vez de mostrar o que foi digitado e gravar outra
        # coisa, que é como se perde a confiança numa tela de cadastro.
        self._normalizar_nomes()
        if self.cpf and not is_valid_cpf(self.cpf):
            raise ValidationError({'cpf': 'CPF inválido. Confira os onze dígitos.'})
        if not self.birth_date and not self.birth_date_unknown_reason and not self.estimated_birth_year:
            raise ValidationError({'birth_date': 'Informe a data de nascimento ou o motivo de ela não constar.'})

    def save(self, *args, **kwargs):
        """Atribui o número do prontuário na primeira gravação.

        Aqui, e não nas views, porque paciente nasce por caminhos demais:
        o cadastro completo, o pré-cadastro que a secretária faz ao
        telefone, a importação, o `seed_demo`. Um paciente sem número
        seria um paciente que ninguém acha pelo número — e descobrir isso
        depois obriga a numerar em lote, o que embaralha a ordem.
        """
        if not self.record_number and self.tenant_id:
            from .numbering import next_record_number

            self.record_number = next_record_number(self.tenant_id)
            if 'update_fields' in kwargs and kwargs['update_fields'] is not None:
                kwargs['update_fields'] = list(kwargs['update_fields']) + ['record_number']
        # Também aqui, e não só no `clean()`: paciente nasce pelo
        # pré-cadastro da agenda, pela importação e pelo `seed_demo`, e
        # nenhum desses chama `full_clean()`. Normalizar num lugar só
        # deixaria metade dos caminhos de fora -- que é exatamente como a
        # grafia solta entrava antes.
        self._normalizar_nomes()
        super().save(*args, **kwargs)

    @property
    def naturalidade(self):
        """Naturalidade em uma linha, ou vazio.

        Vazio, e não "Não informado": quem monta a tela decide como
        mostrar a ausência, e uma string de aviso vinda do modelo acaba
        impressa dentro de um relatório.
        """
        from .naturalidade import rotulo_do_pais

        if self.birth_country and self.birth_country != 'BR':
            pais = rotulo_do_pais(self.birth_country)
            return f'{self.birth_city}, {pais}' if self.birth_city else pais
        if self.birth_city and self.birth_state:
            return f'{self.birth_city}/{self.birth_state}'
        return self.birth_city or ''

    @property
    def has_photo(self):
        """Só o que o cadastro afirma — não confere o disco.

        É lido no cabeçalho da ficha e no do atendimento, em toda abertura
        de tela. Conferir o arquivo aqui seria um acesso a disco por
        renderização para responder a uma pergunta que quase sempre é
        "sim". Quem lê os bytes (`photo.read_photo`) devolve `None`
        quando o arquivo sumiu, e a tela cai na inicial do nome.
        """
        return bool(self.photo_path)

    def __str__(self):
        return f'{self.record_number} — {self.full_name}' if self.record_number else self.full_name


class PatientContact(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='contacts')
    name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=16, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    verified_phone_at = models.DateTimeField(null=True, blank=True)
    verified_email_at = models.DateTimeField(null=True, blank=True)
    authorized_for_documents = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=False)
    valid_until = models.DateTimeField(null=True, blank=True)
    legal_authority = models.BooleanField(default=False)
    authority_evidence = models.CharField(max_length=255, blank=True)

    # ------------------------------------------------ comunicação em massa
    #
    # Consentimento **próprio**, separado de tudo o mais neste modelo.
    #
    # `email_enabled` e `authorized_for_documents` autorizam mensagem
    # transacional: a confirmação do horário que a pessoa marcou, a receita
    # que ela pediu. Comunicação em massa é outra coisa e não se deduz
    # daquelas: quem autorizou receber a própria receita não autorizou
    # receber divulgação.
    #
    # E o dado aqui é sensível por natureza. Constar de uma lista de
    # pacientes de uma clínica de neurologia revela condição de saúde — é
    # dado sensível pela LGPD (art. 5º, II), e o art. 11, I exige
    # consentimento **específico e destacado** para tratá-lo. Um caixa de
    # seleção junto com outros dez não é destacado.
    marketing_opt_in_at = models.DateTimeField(null=True, blank=True)
    #: Como o consentimento foi obtido — "assinou no balcão em 12/03",
    #: "marcou no formulário do site". Sem isso o consentimento é uma data
    #: sem procedência, e não se demonstra o que não se sabe.
    marketing_opt_in_evidence = models.CharField(max_length=255, blank=True)
    marketing_opt_out_at = models.DateTimeField(null=True, blank=True)
    #: Token do link de descadastro. Aleatório e por contato, para o
    #: descadastro ser um clique — exigir que a pessoa faça login para parar
    #: de receber e-mail é obstruir a revogação, que a LGPD garante ser tão
    #: fácil quanto o consentimento (art. 8º, §5º).
    marketing_unsubscribe_token = models.CharField(max_length=64, blank=True, db_index=True)

    @property
    def accepts_marketing(self):
        """Se este contato pode receber comunicação em massa hoje.

        Exige as quatro coisas juntas: e-mail, consentimento dado,
        consentimento não revogado e contato ainda válido. Qualquer uma
        faltando, o contato fica de fora — e a campanha registra por quê.
        """
        from django.utils import timezone

        if not self.email or self.marketing_opt_in_at is None:
            return False
        if self.marketing_opt_out_at is not None:
            return False
        return self.valid_until is None or self.valid_until > timezone.now()

    def clean(self):
        # As três recusas daqui chegam à tela: `PatientContactForm` é
        # `ModelForm`, e o `_post_clean` chama este `clean()` mesmo depois do
        # do formulário. Estavam em inglês, e duas saíam **só** em inglês.
        if not self.phone and not self.email:
            raise ValidationError('Informe telefone ou e-mail.')
        if self.marketing_opt_in_at and not self.marketing_opt_in_evidence:
            raise ValidationError({
                'marketing_opt_in_evidence':
                    'Registre como o consentimento foi obtido. Consentimento sem '
                    'procedência não se demonstra depois.',
            })
        if self.authorized_for_documents and not self.relationship:
            raise ValidationError({
                'relationship': 'Informe a relação com o paciente para autorizar a entrega de documentos.',
            })
        if self.legal_authority and not self.authority_evidence:
            raise ValidationError({
                'authority_evidence': 'Registre a comprovação da representação legal.',
            })

    def __str__(self):
        return f'{self.name} ({self.relationship or "contact"})'


class ObservationKind(models.TextChoices):
    WEIGHT = 'weight', 'Peso'
    HEIGHT = 'height', 'Altura'


class Observation(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='observations')
    kind = models.CharField(max_length=40, choices=ObservationKind.choices)
    numeric_value = models.DecimalField(max_digits=6, decimal_places=2)
    unit = models.CharField(max_length=16)
    observed_at = models.DateTimeField()
    source = models.CharField(max_length=40, default='manual')

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient', 'kind', 'observed_at'], name='patients_obs_lookup_idx'),
        ]

    def clean(self):
        if self.numeric_value is not None and self.numeric_value <= 0:
            raise ValidationError({'numeric_value': 'Informe um valor maior que zero.'})

    def __str__(self):
        return f'{self.kind}={self.numeric_value}{self.unit}'


class PatientCoverage(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='coverages')
    plan = models.ForeignKey(HealthPlan, on_delete=models.PROTECT, related_name='coverages')
    member_number = models.CharField(max_length=60, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)

    def clean(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'A data de término não pode ser anterior à de início.'})

    def __str__(self):
        return f'{self.patient_id} -> {self.plan_id}'
