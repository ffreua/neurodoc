"""Formulários da guia e dos procedimentos.

As listas de código saem do **domínio do XSD da versão** da guia
(`versoes.dominio`) com o rótulo da TUSS (`terminologia`): a guia 4.00.00
oferece "05 — exame ambulatorial", a 4.03.00 oferece "23 — Exame". Código
que a versão não aceita não aparece para ser escolhido.
"""

from django import forms
from django.utils import timezone

from patients.models import PatientCoverage

from . import terminologia, versoes
from .forms import _Bootstrap
from .models import Credenciamento, Guia, ProfissionalTiss, TipoGuia

#: Campo da guia → (tabela TUSS dos rótulos, tipo do XSD).
DOMINIOS = {
    'carater_atendimento': ('23', 'dm_caraterAtendimento'),
    'indicacao_acidente': ('36', 'dm_indicadorAcidente'),
    'tipo_consulta': ('52', 'dm_tipoConsulta'),
    'tipo_atendimento': ('50', 'dm_tipoAtendimento'),
    'motivo_encerramento': ('39', 'dm_motivoSaidaObito'),
    'regime_atendimento': ('76', 'dm_regimeAtendimento'),
    'saude_ocupacional': ('77', 'dm_saudeOcupacional'),
    'ausencia_cod_validacao': ('74', 'dm_ausenciaCodValidacao'),
    'cobertura_especial': ('75', 'dm_cobEsp'),
}
DOMINIOS_ITEM = {
    'via_acesso': ('61', 'dm_viaDeAcesso'),
    'tecnica': ('48', 'dm_tecnicaUtilizada'),
    'tabela': ('87', 'dm_tabela'),
}
OPCIONAIS = {'tipo_consulta', 'motivo_encerramento', 'saude_ocupacional', 'ausencia_cod_validacao',
             'cobertura_especial', 'tipo_atendimento', 'via_acesso', 'tecnica'}

_DATA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def _escolhas(versao, nome, tabela, tipo_dm, opcional):
    dominio = versoes.dominio(versao, tipo_dm)
    if not dominio:
        return None
    pares = terminologia.escolhas(tabela, dominio)
    return ([('', '—')] if opcional else []) + pares


class NovaGuiaForm(_Bootstrap, forms.Form):
    tipo = forms.ChoiceField(label='Tipo de guia', choices=TipoGuia.choices)
    appointment = forms.ChoiceField(label='Atendimento de origem', required=False)

    def __init__(self, *args, horarios=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['appointment'].choices = [('', 'Nenhum — preencher à mão')] + [
            (str(a.id), f'{timezone.localtime(a.starts_at):%d/%m/%Y %H:%M} — {a.get_type_display()} — '
                        f'{a.get_status_display()}')
            for a in horarios
        ]
        self._estilizar()


class GuiaForm(_Bootstrap, forms.ModelForm):
    """O cabeçalho da guia. A indicação clínica não está aqui: é do médico."""

    class Meta:
        model = Guia
        fields = [
            'cobertura', 'credenciamento', 'carteira', 'validade_carteira', 'atendimento_rn',
            'numero_operadora', 'guia_principal', 'data_autorizacao', 'senha', 'validade_senha',
            'cod_validacao', 'ausencia_cod_validacao',
            'contratado_solicitante_tipo', 'contratado_solicitante_codigo', 'contratado_solicitante_nome',
            'solicitante', 'data_solicitacao', 'carater_atendimento', 'cobertura_especial',
            'executante', 'tipo_atendimento', 'indicacao_acidente', 'tipo_consulta',
            'motivo_encerramento', 'regime_atendimento', 'saude_ocupacional', 'observacao',
        ]
        widgets = {
            'validade_carteira': _DATA, 'data_autorizacao': _DATA, 'validade_senha': _DATA,
            'data_solicitacao': _DATA, 'observacao': forms.Textarea(attrs={'rows': 2}),
        }

    #: Campos que só a SP/SADT tem.
    SO_SADT = {
        'guia_principal', 'data_autorizacao', 'senha', 'validade_senha',
        'contratado_solicitante_tipo', 'contratado_solicitante_codigo', 'contratado_solicitante_nome',
        'solicitante', 'data_solicitacao', 'carater_atendimento', 'tipo_atendimento',
        'motivo_encerramento',
    }

    def __init__(self, *args, guia, **kwargs):
        super().__init__(*args, instance=guia, **kwargs)
        tenant_id = guia.tenant_id
        versao = guia.versao_efetiva
        self.fields['cobertura'].queryset = (
            PatientCoverage.objects.filter(tenant_id=tenant_id, patient_id=guia.paciente_id)
            .select_related('plan__insurer')
        )
        self.fields['cobertura'].label_from_instance = (
            lambda c: f'{c.plan.insurer.name} — {c.plan.name}' + (f' · {c.member_number}' if c.member_number else '')
        )
        self.fields['credenciamento'].queryset = (
            Credenciamento.objects.filter(tenant_id=tenant_id, ativo=True).select_related('prestador', 'operadora')
        )
        self.fields['credenciamento'].label_from_instance = (
            lambda c: f'{c.operadora.name} · {c.prestador.nome} · versão {c.versao}'
        )
        profissionais = ProfissionalTiss.objects.filter(tenant_id=tenant_id, ativo=True).order_by('nome')
        self.fields['executante'].queryset = profissionais
        self.fields['solicitante'].queryset = profissionais
        if guia.tipo == TipoGuia.CONSULTA:
            for nome in self.SO_SADT:
                self.fields.pop(nome, None)
        if not versao.startswith('4'):
            for nome in ('regime_atendimento', 'saude_ocupacional', 'cobertura_especial'):
                self.fields.pop(nome, None)
        for nome, (tabela, tipo_dm) in DOMINIOS.items():
            if nome not in self.fields:
                continue
            escolhas = _escolhas(versao, nome, tabela, tipo_dm, nome in OPCIONAIS)
            if escolhas:
                self.fields[nome] = forms.ChoiceField(
                    label=self.fields[nome].label, choices=escolhas, required=nome not in OPCIONAIS,
                )
        self._estilizar()

    def clean_contratado_solicitante_codigo(self):
        return ''.join(c for c in (self.cleaned_data.get('contratado_solicitante_codigo') or '') if c.isalnum()).upper()


class IndicacaoForm(_Bootstrap, forms.Form):
    indicacao_clinica = forms.CharField(
        label='Indicação clínica', max_length=500, required=False, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Vai à operadora na guia. Só o necessário para justificar o pedido.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._estilizar()


class ItemForm(_Bootstrap, forms.Form):
    data_execucao = forms.DateField(label='Data da execução', widget=_DATA)
    hora_inicial = forms.TimeField(label='Hora inicial', required=False, widget=forms.TimeInput(attrs={'type': 'time'}))
    hora_final = forms.TimeField(label='Hora final', required=False, widget=forms.TimeInput(attrs={'type': 'time'}))
    tabela = forms.ChoiceField(label='Tabela', initial='22')
    codigo = forms.CharField(label='Código do procedimento', max_length=10)
    descricao = forms.CharField(label='Descrição', max_length=150, required=False,
                                help_text='Da TUSS quando o código está nela; só se digita para tabela própria.')
    quantidade = forms.IntegerField(label='Quantidade', min_value=1, max_value=999, initial=1)
    via_acesso = forms.ChoiceField(label='Via de acesso', required=False)
    tecnica = forms.ChoiceField(label='Técnica utilizada', required=False)
    fator = forms.DecimalField(label='Fator de redução/acréscimo', max_digits=3, decimal_places=2, initial='1.00',
                               min_value=0.01, help_text='1,00 = cheio; 0,70 reduz 30%; 1,30 acresce 30%.')
    valor_unitario = forms.DecimalField(label='Valor unitário (R$)', max_digits=10, decimal_places=2, required=False,
                                        help_text='Em branco: o honorário do contrato.')
    preco_motivo = forms.CharField(label='Motivo, se o valor for diferente do contrato', max_length=255, required=False)

    def __init__(self, *args, versao, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, (tabela, tipo_dm) in DOMINIOS_ITEM.items():
            escolhas = _escolhas(versao, nome, tabela, tipo_dm, nome in OPCIONAIS)
            if escolhas:
                self.fields[nome].choices = escolhas
        if tipo == TipoGuia.CONSULTA:
            for nome in ('hora_inicial', 'hora_final', 'via_acesso', 'tecnica', 'fator', 'quantidade'):
                self.fields.pop(nome)
        self.fields['codigo'].widget.attrs.update({'autocomplete': 'off', 'data-nd-tiss-tuss': '1'})
        self._estilizar()
