import re
from decimal import Decimal

from django import forms

from base.fields import BrazilianDecimalField
from base.widgets import HTML5DateInput

from base.validators import is_valid_cpf

from .models import (
    HealthPlan, MaritalStatus, Patient, PatientContact, PaymentCategory, ReferralSource,
    SexAtRegistration,
)

UF_CHOICES = [
    ('', 'UF'),
    ('AC', 'AC'), ('AL', 'AL'), ('AP', 'AP'), ('AM', 'AM'), ('BA', 'BA'), ('CE', 'CE'),
    ('DF', 'DF'), ('ES', 'ES'), ('GO', 'GO'), ('MA', 'MA'), ('MT', 'MT'), ('MS', 'MS'),
    ('MG', 'MG'), ('PA', 'PA'), ('PB', 'PB'), ('PR', 'PR'), ('PE', 'PE'), ('PI', 'PI'),
    ('RJ', 'RJ'), ('RN', 'RN'), ('RS', 'RS'), ('RO', 'RO'), ('RR', 'RR'), ('SC', 'SC'),
    ('SP', 'SP'), ('SE', 'SE'), ('TO', 'TO'),
]


class HealthPlanSelect(forms.Select):
    """Select de plano que carrega o tipo e a operadora em cada <option>.

    A tela mostra "Tipo" e "Operadora" do plano escolhido sem uma segunda
    requisição: os dados já vêm no HTML, lidos do plano cadastrado.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._plan_data = {}

    def load_plan_data(self, queryset):
        self._plan_data = {
            str(plan.pk): (plan.get_kind_display(), plan.insurer.name)
            for plan in queryset
        }

    def create_option(self, name, value, *args, **kwargs):
        option = super().create_option(name, value, *args, **kwargs)
        data = self._plan_data.get(str(value))
        if data:
            option['attrs']['data-kind'] = data[0]
            option['attrs']['data-insurer'] = data[1]
        return option


class PatientForm(forms.ModelForm):
    """Cadastro do paciente, incluindo a cobertura quando o pagamento é por plano.

    A cobertura vive em `PatientCoverage`, mas quem cadastra o paciente
    precisa informá-la na mesma tela: separar as duas coisas obrigava a
    secretaria a salvar o paciente e só depois procurar onde lançar a
    carteirinha. Os campos `coverage_*` abaixo não são do modelo Patient;
    a view os transforma em uma `PatientCoverage` na mesma transação.
    """

    # Declarados aqui, e não derivados do modelo, porque a tela envia o valor
    # com máscara ("123.456.789-09", "01310-100"): o max_length do modelo
    # recusaria a máscara antes de qualquer clean_* ter chance de removê-la.
    cpf = forms.CharField(
        label='CPF', max_length=14, required=True,
        help_text='Obrigatório e conferido pelos dígitos verificadores.',
        widget=forms.TextInput(
            attrs={'placeholder': 'Ex.: 123.456.789-09', 'inputmode': 'numeric', 'maxlength': '14'},
        ),
    )
    postal_code = forms.CharField(
        label='CEP', max_length=9, required=False,
        help_text='Ao digitar os 8 dígitos, município e UF são preenchidos automaticamente.',
        widget=forms.TextInput(
            attrs={'placeholder': 'Ex.: 01310-100', 'inputmode': 'numeric', 'maxlength': '9'},
        ),
    )
    state = forms.ChoiceField(label='UF', choices=UF_CHOICES, required=False)

    coverage_plan = forms.ModelChoiceField(
        label='Plano de saúde', queryset=HealthPlan.objects.none(), required=False,
        empty_label='Selecione o plano', widget=HealthPlanSelect,
    )
    coverage_member_number = forms.CharField(
        label='Número da carteirinha', max_length=60, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Ex.: 0123456789012345'}),
    )
    coverage_starts_on = forms.DateField(
        label='Início', required=False, help_text='Início da vigência.',
        widget=HTML5DateInput(),
    )
    coverage_ends_on = forms.DateField(
        label='Validade', required=False, help_text='Validade da carteirinha.',
        widget=HTML5DateInput(),
    )

    # Peso e altura não são campos do paciente: são **medidas com data**, e
    # viram `Observation`. A ficha mostrava o IMC sem que houvesse por onde
    # informar peso e altura — o cálculo existia e nunca tinha o que calcular.
    # Ficam opcionais: pesar na primeira consulta não é sempre possível.
    weight_kg = BrazilianDecimalField(
        label='Peso', required=False, min_value=Decimal('0.5'), max_value=Decimal('500'),
        decimal_places=2, help_text='Em quilogramas. Ex.: 82,5',
        widget=forms.NumberInput(attrs={'placeholder': 'Ex.: 82,5', 'step': '0.1', 'inputmode': 'decimal'}),
    )
    height_m = BrazilianDecimalField(
        label='Altura', required=False, min_value=Decimal('0.3'), max_value=Decimal('2.6'),
        decimal_places=2, help_text='Em metros. Ex.: 1,75',
        widget=forms.NumberInput(attrs={'placeholder': 'Ex.: 1,75', 'step': '0.01', 'inputmode': 'decimal'}),
    )

    class Meta:
        model = Patient
        fields = [
            'full_name', 'birth_date', 'birth_date_unknown_reason', 'estimated_birth_year',
            'sex_at_registration', 'cpf', 'identity_number', 'mother_name',
            'postal_code', 'street', 'number', 'complement', 'district', 'city', 'state', 'country',
            'referral_source', 'referral_details', 'marital_status', 'occupation',
            'payment_category', 'responsible_membership', 'administrative_notes',
        ]
        labels = {
            'full_name': 'Nome completo',
            'birth_date': 'Data de nascimento',
            'birth_date_unknown_reason': 'Motivo de a data ser desconhecida',
            'estimated_birth_year': 'Ano de nascimento estimado',
            'sex_at_registration': 'Sexo no cadastro',
            'cpf': 'CPF',
            'identity_number': 'Documento de identidade (RG)',
            'mother_name': 'Nome da mãe',
            'postal_code': 'CEP',
            'street': 'Logradouro',
            'number': 'Número',
            'complement': 'Complemento',
            'district': 'Bairro',
            'city': 'Município',
            'state': 'UF',
            'country': 'País',
            'referral_source': 'Como chegou à clínica',
            'referral_details': 'Detalhes do encaminhamento',
            'marital_status': 'Estado civil',
            'occupation': 'Ocupação',
            'payment_category': 'Forma de pagamento',
            'responsible_membership': 'Médico responsável',
            'administrative_notes': 'Observações administrativas',
        }
        widgets = {
            'full_name': forms.TextInput(attrs={'placeholder': 'Ex.: Maria Aparecida de Souza'}),
            'birth_date': HTML5DateInput(),
            'birth_date_unknown_reason': forms.TextInput(
                attrs={'placeholder': 'Ex.: paciente sem documentos na admissão'},
            ),
            'estimated_birth_year': forms.NumberInput(attrs={'placeholder': 'Ex.: 1978'}),
            'identity_number': forms.TextInput(attrs={'placeholder': 'Ex.: 12.345.678-9'}),
            'mother_name': forms.TextInput(attrs={'placeholder': 'Ex.: Joana de Souza'}),
            'street': forms.TextInput(attrs={'placeholder': 'Ex.: Avenida Paulista'}),
            'number': forms.TextInput(attrs={'placeholder': 'Ex.: 1578'}),
            'complement': forms.TextInput(attrs={'placeholder': 'Ex.: apto 42, bloco B'}),
            'district': forms.TextInput(attrs={'placeholder': 'Ex.: Bela Vista'}),
            'city': forms.TextInput(attrs={'placeholder': 'Ex.: São Paulo'}),
            'country': forms.TextInput(attrs={'placeholder': 'BR', 'maxlength': '2'}),
            'referral_details': forms.TextInput(attrs={'placeholder': 'Ex.: Dr. Carlos Lima (neurologia)'}),
            'occupation': forms.TextInput(attrs={'placeholder': 'Ex.: professora'}),
            'administrative_notes': forms.Textarea(
                attrs={'rows': 3, 'placeholder': 'Ex.: prefere contato por WhatsApp no período da tarde'},
            ),
        }

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        from tenancy.models import Membership, MembershipStatus, Role

        self.tenant_id = tenant_id

        doctors = Membership.objects.none()
        plans = HealthPlan.objects.none()
        if tenant_id is not None:
            doctors = Membership.objects.filter(
                tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
            ).select_related('user')
            plans = (
                HealthPlan.objects
                .filter(tenant_id=tenant_id, active=True)
                .select_related('insurer')
                .order_by('insurer__name', 'name')
            )

        self.fields['responsible_membership'].queryset = doctors
        self.fields['responsible_membership'].required = False
        self.fields['responsible_membership'].empty_label = 'Selecione o médico'
        self.fields['responsible_membership'].label_from_instance = (
            lambda membership: membership.user.get_full_name() or membership.user.email
        )

        self.fields['coverage_plan'].queryset = plans
        self.fields['coverage_plan'].label_from_instance = (
            lambda plan: f'{plan.insurer.name} — {plan.name}'
        )
        self.fields['coverage_plan'].widget.load_plan_data(plans)
        self.has_plans = plans.exists() if tenant_id is not None else False

        # CPF identifica o paciente em documento, guia e cobrança: exigido no
        # cadastro, ainda que o modelo aceite nulo por causa dos registros
        # criados antes desta regra.
        self.fields['cpf'].required = True

        self.fields['country'].required = False
        if not self.instance.pk and not self.initial.get('country'):
            self.fields['country'].initial = 'BR'

        # Preenche o bloco de plano a partir da cobertura vigente ao editar.
        if self.instance.pk:
            # Peso e altura vêm da última medida registrada, **também quando o
            # formulário está vinculado**. Não é só para a tela abrir
            # preenchida: `changed_data` compara o enviado com o `initial`, e
            # é isso que impede salvar a ficha sem tocar no peso de gravar uma
            # segunda medida idêntica na série. Com o `initial` só no caminho
            # não vinculado, todo salvamento parecia uma medida nova.
            from .observations import latest_observation
            from .models import ObservationKind

            last_weight = latest_observation(self.instance, ObservationKind.WEIGHT)
            last_height = latest_observation(self.instance, ObservationKind.HEIGHT)
            if last_weight is not None:
                self.fields['weight_kg'].initial = last_weight.numeric_value
                self.fields['weight_kg'].help_text = (
                    f'Última medida: {last_weight.numeric_value} kg em '
                    f'{last_weight.observed_at.strftime("%d/%m/%Y")}. Alterar registra uma nova.'
                )
            if last_height is not None:
                self.fields['height_m'].initial = last_height.numeric_value
                self.fields['height_m'].help_text = (
                    f'Última medida: {last_height.numeric_value} m em '
                    f'{last_height.observed_at.strftime("%d/%m/%Y")}. Alterar registra uma nova.'
                )

        if self.instance.pk and not self.is_bound:
            coverage = self.instance.coverages.order_by('-starts_on', '-created_at').first()
            if coverage is not None:
                self.fields['coverage_plan'].initial = coverage.plan_id
                self.fields['coverage_member_number'].initial = coverage.member_number
                self.fields['coverage_starts_on'].initial = coverage.starts_on
                self.fields['coverage_ends_on'].initial = coverage.ends_on

    def clean_full_name(self):
        name = (self.cleaned_data['full_name'] or '').strip()
        if not name:
            raise forms.ValidationError('Informe o nome completo do paciente.')
        return name

    def clean_cpf(self):
        raw = (self.cleaned_data.get('cpf') or '').strip()
        digits = re.sub(r'\D', '', raw)
        if not digits:
            raise forms.ValidationError('Informe o CPF do paciente.')
        if len(digits) != 11:
            raise forms.ValidationError('O CPF tem 11 dígitos. Informe todos, com ou sem pontuação.')
        if not is_valid_cpf(digits):
            raise forms.ValidationError('CPF inválido: os dígitos verificadores não conferem.')
        duplicate = Patient.objects.filter(tenant_id=self.tenant_id, cpf=digits)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        existing = duplicate.first()
        if existing is not None:
            raise forms.ValidationError(
                f'Este CPF já está cadastrado para {existing.full_name}.',
            )
        return digits

    def clean_postal_code(self):
        return re.sub(r'\D', '', self.cleaned_data.get('postal_code') or '')

    def clean_country(self):
        # Opcional na tela; o modelo não aceita vazio e o padrão é Brasil.
        return (self.cleaned_data.get('country') or 'BR').strip().upper()[:2]

    def clean_birth_date(self):
        from django.utils import timezone
        value = self.cleaned_data.get('birth_date')
        if value and value > timezone.now().date():
            raise forms.ValidationError('A data de nascimento não pode estar no futuro.')
        return value

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('payment_category')
        plan = cleaned.get('coverage_plan')

        if category == PaymentCategory.PLAN:
            if plan is None:
                self.add_error('coverage_plan', 'Escolha o plano de saúde do paciente.')
            if not (cleaned.get('coverage_member_number') or '').strip():
                self.add_error('coverage_member_number', 'Informe o número da carteirinha.')
        elif plan is not None:
            self.add_error(
                'payment_category',
                'Um plano foi escolhido: mude a forma de pagamento para "Plano" ou limpe o plano.',
            )

        starts_on = cleaned.get('coverage_starts_on')
        ends_on = cleaned.get('coverage_ends_on')
        if starts_on and ends_on and ends_on < starts_on:
            self.add_error('coverage_ends_on', 'A validade não pode ser anterior ao início da vigência.')

        if not cleaned.get('birth_date') and not (
            cleaned.get('birth_date_unknown_reason') or cleaned.get('estimated_birth_year')
        ):
            self.add_error(
                'birth_date',
                'Informe a data de nascimento ou, se ela for desconhecida, o motivo e o ano estimado.',
            )
        return cleaned

    @property
    def coverage_data(self):
        """Dados da cobertura a gravar, ou None quando não é atendimento por plano."""
        if self.cleaned_data.get('payment_category') != PaymentCategory.PLAN:
            return None
        plan = self.cleaned_data.get('coverage_plan')
        if plan is None:
            return None
        return {
            'plan_id': plan.id,
            'member_number': (self.cleaned_data.get('coverage_member_number') or '').strip(),
            'starts_on': self.cleaned_data.get('coverage_starts_on'),
            'ends_on': self.cleaned_data.get('coverage_ends_on'),
        }

    @property
    def measurements(self):
        """Medidas a **registrar**, como triplas (tipo, valor, unidade).

        Duas regras aqui:

        - devolve só o que foi preenchido — peso sem altura já serve para
          acompanhar a evolução, e exigir os dois faria perder a medida que
          existe;
        - na edição, devolve só o que **mudou**. Peso e altura formam uma
          série com data; salvar a ficha sem tocar no peso não pode inserir
          uma segunda medida idêntica, que apareceria como "pesou de novo
          hoje" e sujaria a evolução.
        """
        from .models import ObservationKind

        rows = []
        for field, kind, unit in (
            ('weight_kg', ObservationKind.WEIGHT, 'kg'),
            ('height_m', ObservationKind.HEIGHT, 'm'),
        ):
            value = self.cleaned_data.get(field)
            if not value:
                continue
            if self.instance.pk and field not in self.changed_data:
                continue
            rows.append((kind, value, unit))
        return rows


class PatientContactForm(forms.ModelForm):
    class Meta:
        model = PatientContact
        fields = [
            'name', 'relationship', 'phone', 'email', 'authorized_for_documents',
            'sms_enabled', 'email_enabled', 'legal_authority', 'authority_evidence',
        ]
        labels = {
            'name': 'Nome',
            'relationship': 'Relação com o paciente',
            'phone': 'Telefone',
            'email': 'E-mail',
            'authorized_for_documents': 'Autorizado a receber documentos',
            'sms_enabled': 'Aceita SMS',
            'email_enabled': 'Aceita e-mail',
            'legal_authority': 'Representante legal',
            'authority_evidence': 'Comprovação da representação',
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('phone') and not cleaned.get('email'):
            raise forms.ValidationError('Informe telefone ou e-mail.')
        return cleaned


class PatientCoverageForm(forms.Form):
    # `empty_label` explícito: sem ele o Django escreve "---------", que não
    # diz o que se espera do campo.
    plan = forms.ModelChoiceField(
        queryset=None, label='Plano de saúde', empty_label='Selecione o plano',
    )
    member_number = forms.CharField(label='Matrícula', max_length=60, required=False)
    starts_on = forms.DateField(label='Início da vigência', widget=HTML5DateInput())
    ends_on = forms.DateField(
        label='Fim da vigência', widget=HTML5DateInput(), required=False,
    )

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import HealthPlan

        queryset = HealthPlan.objects.none()
        if tenant_id is not None:
            queryset = HealthPlan.objects.filter(tenant_id=tenant_id, active=True).select_related('insurer')
        self.fields['plan'].queryset = queryset
        self.fields['plan'].label_from_instance = lambda plan: f'{plan.insurer.name} — {plan.name}'


class PatientMeasurementForm(forms.Form):
    """Registro rápido de peso e altura na ficha.

    Existe separado do cadastro porque peso é medida de acompanhamento: muda
    entre consultas e forma uma série com data. `observed_on` permite lançar
    a medida do dia da consulta quando o registro é feito depois.
    """

    weight_kg = BrazilianDecimalField(
        label='Peso (kg)', required=False, min_value=Decimal('0.5'), max_value=Decimal('500'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={'placeholder': '82,5', 'step': '0.1', 'inputmode': 'decimal'}),
    )
    height_m = BrazilianDecimalField(
        label='Altura (m)', required=False, min_value=Decimal('0.3'), max_value=Decimal('2.6'),
        decimal_places=2,
        widget=forms.NumberInput(attrs={'placeholder': '1,75', 'step': '0.01', 'inputmode': 'decimal'}),
    )
    observed_on = forms.DateField(
        label='Data da medida', required=False, widget=HTML5DateInput(),
        help_text='Em branco, vale hoje.',
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('weight_kg') and not cleaned.get('height_m'):
            raise forms.ValidationError('Informe o peso, a altura, ou os dois.')
        observed_on = cleaned.get('observed_on')
        if observed_on:
            from django.utils import timezone

            if observed_on > timezone.now().date():
                self.add_error('observed_on', 'A medida não pode ser de uma data futura.')
        return cleaned

    @property
    def measurements(self):
        from .models import ObservationKind

        rows = []
        if self.cleaned_data.get('weight_kg'):
            rows.append((ObservationKind.WEIGHT, self.cleaned_data['weight_kg'], 'kg'))
        if self.cleaned_data.get('height_m'):
            rows.append((ObservationKind.HEIGHT, self.cleaned_data['height_m'], 'm'))
        return rows
