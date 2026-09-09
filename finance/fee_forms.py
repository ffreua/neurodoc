"""Formulário da tabela de honorários.

O modelo já existia (`FeeSchedule`) e a resolução de preço também
(`finance.pricing.resolve_price`), com a regra mais específica vencendo a
mais geral. O que faltava era a tela: sem ela, definir quanto custa uma
consulta exigia o admin técnico do Django, que é de quem opera o servidor.
"""

from datetime import date

from django import forms

from base.widgets import HTML5DateInput
from catalogs.models import CatalogSystem, ProcedureCode
from patients.models import HealthPlan
from tenancy.models import Membership, MembershipStatus, Role

from .models import PaymentCategory


class FeeScheduleForm(forms.Form):
    """Uma regra de preço.

    Os três primeiros campos são opcionais **de propósito**: em branco
    significa "vale para qualquer um", e é assim que se escreve a regra
    geral da clínica. `resolve_price` procura da combinação mais específica
    para a mais geral, então uma regra sem médico, sem plano e sem
    procedimento é o piso que responde quando nenhuma outra se aplica.
    """

    physician = forms.ChoiceField(label='Médico', required=False)
    payment_category = forms.ChoiceField(label='Forma de pagamento', choices=PaymentCategory.choices)
    plan = forms.ChoiceField(label='Plano', required=False)
    procedure = forms.ChoiceField(label='Procedimento', required=False)
    gross_amount = forms.DecimalField(
        label='Valor cheio (R$)', max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0,00'}),
        help_text='O que a consulta ou o procedimento custa.',
    )
    doctor_share_amount = forms.DecimalField(
        label='Repasse ao médico (R$)', max_digits=12, decimal_places=2, min_value=0,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0,00'}),
        help_text='Quanto desse valor fica com o médico. Igual ao valor cheio quando não há '
                  'divisão com a clínica.',
    )
    effective_from = forms.DateField(
        label='Vale a partir de', widget=HTML5DateInput(),
        help_text='Tabela nova não altera o que já foi cobrado — ela passa a valer desta data '
                  'em diante.',
    )
    effective_to = forms.DateField(
        label='Até', required=False, widget=HTML5DateInput(),
        help_text='Em branco, vale por prazo indeterminado.',
    )

    def __init__(self, *args, tenant_id=None, context=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant_id = tenant_id
        self.access_context = context
        self.fields['effective_from'].initial = date.today()

        self._physicians = {
            str(m.id): m for m in
            Membership.objects.filter(
                tenant_id=tenant_id, status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
            ).select_related('user').order_by('user__first_name', 'user__email')
        }
        self.fields['physician'].choices = [('', 'Todos os médicos (regra geral)')] + [
            (pk, m.user.get_full_name() or m.user.email) for pk, m in self._physicians.items()
        ]

        self._plans = {
            str(p.id): p for p in
            HealthPlan.objects.filter(tenant_id=tenant_id, active=True)
            .select_related('insurer').order_by('insurer__name', 'name')
        }
        self.fields['plan'].choices = [('', 'Qualquer plano')] + [
            (pk, f'{p.insurer.name} — {p.name}') for pk, p in self._plans.items()
        ]

        self._procedures = {
            str(p.id): p for p in
            ProcedureCode.objects.filter(
                release__system=CatalogSystem.TUSS, release__status='active', active=True,
            ).order_by('code')
        }
        self.fields['procedure'].choices = [('', 'Consulta (sem procedimento)')] + [
            (pk, f'{p.code} — {p.description[:70]}') for pk, p in self._procedures.items()
        ]

    # ------------------------------------------------------------ objetos
    def physician_object(self):
        return self._physicians.get(self.cleaned_data.get('physician') or '')

    def plan_object(self):
        return self._plans.get(self.cleaned_data.get('plan') or '')

    def procedure_object(self):
        return self._procedures.get(self.cleaned_data.get('procedure') or '')

    # ------------------------------------------------------------ validação
    def clean_physician(self):
        """Quem pode definir preço de quem.

        Verificado aqui e não só na view porque o `<select>` mostra a lista
        inteira para quem administra a clínica, e o mesmo formulário é
        enviado pelo médico — que vê apenas o próprio nome, mas pode
        trocar o valor no envio.
        """
        from tenancy.permissions import can_set_fee_for

        value = self.cleaned_data.get('physician') or ''
        if value and value not in self._physicians:
            raise forms.ValidationError('Este médico não tem vínculo ativo nesta clínica.')
        if not can_set_fee_for(self.access_context, value or None):
            if not value:
                raise forms.ValidationError(
                    'A regra geral, que vale para a clínica inteira, é definida por quem '
                    'administra a clínica.',
                )
            raise forms.ValidationError('Você só define o valor das próprias consultas.')
        return value

    def clean(self):
        cleaned = super().clean()
        bruto = cleaned.get('gross_amount')
        repasse = cleaned.get('doctor_share_amount')
        if bruto is not None and repasse is not None and repasse > bruto:
            # Repasse maior que o valor cheio é a clínica pagando para
            # atender. Acontece por digitar os dois campos ao contrário, e
            # o erro só apareceria no fechamento do mês.
            self.add_error(
                'doctor_share_amount',
                'O repasse não pode ser maior que o valor cheio. Confira se os dois '
                'campos não foram trocados.',
            )
        inicio = cleaned.get('effective_from')
        fim = cleaned.get('effective_to')
        if inicio and fim and fim < inicio:
            self.add_error('effective_to', 'A data final não pode ser anterior à inicial.')

        categoria = cleaned.get('payment_category')
        if categoria == PaymentCategory.PRIVATE and cleaned.get('plan'):
            self.add_error(
                'plan',
                'Particular e plano são formas de pagamento diferentes. Escolha "Plano" '
                'acima, ou deixe o plano em branco.',
            )
        if categoria == PaymentCategory.INSURANCE and not cleaned.get('plan'):
            # Uma regra de plano sem plano vale para todos os convênios ao
            # mesmo tempo — quase nunca é o que se quis dizer, e o preço
            # errado só aparece na fatura.
            self.add_error('plan', 'Escolha o plano a que este valor se refere.')
        return cleaned


class FeeScheduleCloseForm(forms.Form):
    """Encerra uma regra numa data, em vez de apagá-la.

    Honorário é história: o recebimento guarda um retrato do que valia
    quando foi gerado (`Receivable.fee_snapshot`), e a regra em si é o que
    explica de onde aquele retrato veio. Apagar a linha deixa o
    recebimento antigo sem origem legível.
    """

    effective_to = forms.DateField(
        label='Encerrar em', widget=HTML5DateInput(),
        help_text='Último dia em que este valor vale.',
    )
