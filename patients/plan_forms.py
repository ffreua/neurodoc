"""Formulários do cadastro de convênios e planos.

Separados de `patients/forms.py` porque aquele arquivo é a ficha do
paciente — o que a recepção preenche com a pessoa na frente. Isto é
cadastro de retaguarda: existe uma vez, muda pouco, e é consumido pela
ficha e pela tabela de honorários.
"""

from django import forms

from .models import HealthPlan, HealthPlanKind, Insurer


class InsurerForm(forms.ModelForm):
    class Meta:
        model = Insurer
        fields = ['name', 'ans_registration', 'active']
        labels = {
            'name': 'Convênio',
            'ans_registration': 'Registro na ANS',
            'active': 'Aceito pela clínica',
        }
        help_texts = {
            'ans_registration': 'Opcional. Aparece na guia e identifica a operadora sem ambiguidade '
                                'quando duas têm nome parecido.',
            'active': 'Desmarcado, o convênio some das listas de escolha e continua nos cadastros '
                      'que já o usam.',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex.: Bradesco Saúde'}),
            'ans_registration': forms.TextInput(attrs={'placeholder': 'Ex.: 005711'}),
        }

    def clean_name(self):
        return (self.cleaned_data['name'] or '').strip()


class HealthPlanForm(forms.ModelForm):
    """Um plano dentro de um convênio.

    `insurer` tem as opções restritas ao inquilino no `__init__`, e não por
    `limit_choices_to`: o formulário não sabe o inquilino em tempo de
    definição da classe, e um `<select>` montado sem esse filtro ofereceria
    convênio de outra clínica — que o `full_clean` recusaria, mas depois de
    a pessoa ter escolhido.
    """

    class Meta:
        model = HealthPlan
        fields = ['insurer', 'name', 'kind', 'active', 'administrative_notes']
        labels = {
            'insurer': 'Convênio',
            'name': 'Plano',
            'kind': 'Segmentação assistencial',
            'active': 'Aceito pela clínica',
            'administrative_notes': 'Observações administrativas',
        }
        help_texts = {
            'kind': 'Segmentação da ANS. "Não informada" é resposta válida — melhor do que '
                    'escolher uma segmentação errada por precisar preencher.',
            'administrative_notes': 'Carência, coparticipação, exigência de guia, telefone da '
                                    'autorização. Aparece a quem marca e a quem cobra.',
        }
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex.: Nacional Plus Enfermaria'}),
            'administrative_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Ex.: exige guia autorizada com 48h de antecedência; '
                               'coparticipação de R$ 40 por consulta.',
            }),
        }

    def __init__(self, *args, tenant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = HealthPlanKind.choices
        queryset = Insurer.objects.none()
        if tenant_id is not None:
            queryset = Insurer.objects.filter(tenant_id=tenant_id).order_by('name')
        self.fields['insurer'].queryset = queryset
        self.fields['insurer'].empty_label = 'Escolha o convênio'

    def clean_name(self):
        return (self.cleaned_data['name'] or '').strip()
