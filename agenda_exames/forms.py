"""Formulários da agenda de exames. Toda lista de escolha é da clínica da sessão."""

from datetime import datetime

from django import forms
from django.utils import timezone

from .models import DURACAO_MAXIMA_MINUTOS, Cobranca, Janela, Recurso


def _profissionais(tenant_id):
    from tiss.models import ProfissionalTiss

    return ProfissionalTiss.objects.filter(tenant_id=tenant_id, ativo=True).order_by('nome')


class RecursoForm(forms.ModelForm):
    class Meta:
        model = Recurso
        fields = ['nome', 'tipo', 'duracao_padrao', 'intervalo', 'codigo_tuss', 'descricao_tuss',
                  'executante_padrao', 'ativo']
        labels = {'nome': 'Nome da agenda', 'tipo': 'Tipo de exame', 'executante_padrao': 'Quem costuma executar'}
        help_texts = {
            'duracao_padrao': 'A polissonografia costuma ter 600 minutos (10 horas).',
            'codigo_tuss': 'O procedimento que a reserva sugere e que vai na guia.',
        }

    def __init__(self, *args, tenant_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['executante_padrao'].queryset = _profissionais(tenant_id)
        self.fields['executante_padrao'].required = False
        self.fields['duracao_padrao'].max_value = DURACAO_MAXIMA_MINUTOS
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-check-input' if isinstance(f.widget, forms.CheckboxInput)
                                      else 'form-select' if isinstance(f.widget, forms.Select) else 'form-control')

    def clean_duracao_padrao(self):
        v = self.cleaned_data['duracao_padrao']
        if not 5 <= v <= DURACAO_MAXIMA_MINUTOS:
            raise forms.ValidationError('A duração vai de 5 minutos a 24 horas (1.440 minutos).')
        return v


class JanelaForm(forms.ModelForm):
    class Meta:
        model = Janela
        fields = ['dia_semana', 'inicio', 'fim']
        labels = {'dia_semana': 'Dia', 'inicio': 'Das', 'fim': 'Até'}
        help_texts = {'fim': 'Fim antes do início é atravessar a meia-noite (ex.: 20:00 até 07:00).'}
        widgets = {
            'inicio': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'fim': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'dia_semana': forms.Select(attrs={'class': 'form-select'}),
        }


class BloqueioForm(forms.Form):
    inicio = forms.DateTimeField(label='De', widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}))
    fim = forms.DateTimeField(label='Até', widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}))
    motivo = forms.CharField(label='Motivo', max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))


def _cobertura_choices(paciente):
    if paciente is None:
        return []
    return [(str(c.id), f'{c.plan.insurer.name} — {c.plan.name} (carteira final {c.member_number[-4:]})')
            for c in paciente.coverages.select_related('plan__insurer').order_by('-starts_on')]


class ReservaForm(forms.Form):
    paciente = forms.UUIDField(widget=forms.HiddenInput)
    data = forms.DateField(label='Data', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    hora = forms.TimeField(label='Início', widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}))
    duracao = forms.IntegerField(label='Duração (minutos)', min_value=5, max_value=DURACAO_MAXIMA_MINUTOS,
                                 widget=forms.NumberInput(attrs={'class': 'form-control'}))
    codigo_tuss = forms.CharField(label='Código TUSS', max_length=10, required=False,
                                  widget=forms.TextInput(attrs={'class': 'form-control'}))
    descricao = forms.CharField(label='Procedimento', max_length=150, required=False,
                                widget=forms.TextInput(attrs={'class': 'form-control'}))
    solicitante = forms.ModelChoiceField(label='Quem pediu o exame', queryset=None, required=False,
                                         widget=forms.Select(attrs={'class': 'form-select'}))
    cobranca = forms.ChoiceField(label='Forma de cobrança', required=False,
                                 choices=[('', 'Decidir depois')] + list(Cobranca.choices),
                                 widget=forms.Select(attrs={'class': 'form-select'}))
    cobertura = forms.ChoiceField(label='Convênio', required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    observacao = forms.CharField(label='Observação (preparo, acompanhante)', max_length=500, required=False,
                                 widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    encaixe = forms.BooleanField(label='Encaixe fora do horário da agenda', required=False,
                                 widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    motivo_encaixe = forms.CharField(label='Motivo do encaixe', max_length=255, required=False,
                                     widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, tenant_id, paciente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['solicitante'].queryset = _profissionais(tenant_id)
        self.fields['cobertura'].choices = [('', '—')] + _cobertura_choices(paciente)

    def inicio(self):
        d = self.cleaned_data
        return timezone.make_aware(datetime.combine(d['data'], d['hora']))


class RemarcarForm(forms.Form):
    data = forms.DateField(label='Nova data', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    hora = forms.TimeField(label='Novo início', widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}))
    encaixe = forms.BooleanField(label='Encaixe fora do horário', required=False,
                                 widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    motivo_encaixe = forms.CharField(label='Motivo do encaixe', max_length=255, required=False,
                                     widget=forms.TextInput(attrs={'class': 'form-control'}))

    def inicio(self):
        d = self.cleaned_data
        return timezone.make_aware(datetime.combine(d['data'], d['hora']))
