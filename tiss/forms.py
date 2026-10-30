"""Formulários da configuração TISS.

Toda lista de escolha é restrita à clínica da sessão **no formulário**, e o
banco confere de novo pela chave composta: um `id` de operadora de outra
clínica forjado no POST não passa da validação, e se passasse, não passaria
do `INSERT`.
"""

from django import forms

from patients.models import Insurer
from tenancy.models import Membership, MembershipStatus, Role

from . import versoes
from .models import Credenciamento, Prestador, ProfissionalTiss
from .validators import normalizar_cnpj


class _Bootstrap:
    def _estilizar(self):
        for campo in self.fields.values():
            classe = 'form-select' if isinstance(campo.widget, forms.Select) else 'form-control'
            if isinstance(campo.widget, forms.CheckboxInput):
                classe = 'form-check-input'
            campo.widget.attrs.setdefault('class', classe)


class PrestadorForm(_Bootstrap, forms.ModelForm):
    # Com máscara o CNPJ tem 18 caracteres e o CPF, 14: o campo aceita o que
    # se digita, e `Prestador.clean` normaliza antes de validar e gravar.
    cnpj = forms.CharField(label='CNPJ', max_length=18, required=False)
    cpf = forms.CharField(label='CPF', max_length=14, required=False)

    class Meta:
        model = Prestador
        fields = ['nome', 'tipo_pessoa', 'cnpj', 'cpf', 'cnes', 'ativo']
        help_texts = {
            'cnpj': 'Aceita o CNPJ alfanumérico; ele só sai no XML a partir da versão 4.03.00.',
            'cnes': 'Sete dígitos. Em branco, a guia leva 9999999, como a ANS manda para quem não tem.',
        }

    def __init__(self, *args, tenant_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant_id = tenant_id
        self._estilizar()

    # Normalizados aqui, e não só no modelo: o Django confere o tamanho do
    # campo do modelo (14) antes de chamar `Prestador.clean`.
    def clean_cnpj(self):
        return normalizar_cnpj(self.cleaned_data.get('cnpj'))

    def clean_cpf(self):
        return ''.join(c for c in (self.cleaned_data.get('cpf') or '') if c.isdigit())


class CredenciamentoForm(_Bootstrap, forms.ModelForm):
    versao = forms.ChoiceField(label='Versão do padrão TISS', choices=versoes.escolhas())
    aceite_motivo = forms.CharField(
        label='A operadora aceita esta versão histórica? Registre como você sabe',
        required=False, max_length=255,
        help_text='Só para 3.04.00 e 3.05.00, que não constam de nenhuma versão vigente da ANS. '
                  'Ex.: "portal da Hapvida recebeu o lote de 10/2026 nesta versão".',
    )

    class Meta:
        model = Credenciamento
        fields = [
            'prestador', 'operadora', 'identificacao', 'codigo_na_operadora', 'versao',
            'ciclo', 'canal', 'limite_guias_por_lote', 'portal_url', 'instrucoes',
            'vigencia_inicio', 'vigencia_fim', 'ativo',
        ]
        widgets = {
            'vigencia_inicio': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'vigencia_fim': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'instrucoes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, tenant_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant_id = tenant_id
        self.fields['prestador'].queryset = Prestador.objects.filter(tenant_id=tenant_id, ativo=True)
        self.fields['operadora'].queryset = Insurer.objects.filter(tenant_id=tenant_id).order_by('name')
        self.fields['operadora'].label = 'Operadora (convênio)'
        if self.instance.aceite_versao_motivo:
            self.fields['aceite_motivo'].initial = self.instance.aceite_versao_motivo
        self._estilizar()

    def clean(self):
        dados = super().clean()
        codigo = dados.get('versao')
        if codigo and versoes.versao(codigo).historica and not (dados.get('aceite_motivo') or '').strip():
            self.add_error(
                'aceite_motivo',
                'Versão histórica: registre como você sabe que a operadora a aceita. '
                'Sem isso, o XML sai só para conferência, não para cobrança.',
            )
        prestador, operadora = dados.get('prestador'), dados.get('operadora')
        if dados.get('ativo') and prestador and operadora:
            repetido = Credenciamento.objects.filter(
                tenant_id=self.instance.tenant_id, prestador=prestador, operadora=operadora, ativo=True,
            ).exclude(id=self.instance.id).exists()
            if repetido:
                self.add_error(
                    'operadora',
                    'Este prestador já tem um credenciamento ativo com esta operadora. '
                    'Edite aquele, ou desative-o antes.',
                )
        return dados


class ProfissionalForm(_Bootstrap, forms.ModelForm):
    cpf = forms.CharField(label='CPF', max_length=14, required=False)
    cbo = forms.CharField(label='CBO', max_length=7)

    class Meta:
        model = ProfissionalTiss
        fields = ['nome', 'conselho', 'numero_conselho', 'uf', 'cbo', 'cpf', 'membership', 'ativo']
        labels = {'membership': 'Usuário da clínica (vazio = profissional externo)'}
        help_texts = {
            'cbo': 'Seis dígitos, sem ponto. 225112 = médico neurologista; 225124 = médico pediatra.',
        }

    def __init__(self, *args, tenant_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant_id = tenant_id
        self.fields['membership'].queryset = (
            Membership.objects.filter(tenant_id=tenant_id, status=MembershipStatus.ACTIVE)
            .select_related('user').order_by('user__first_name')
        )
        self.fields['membership'].label_from_instance = (
            lambda m: f'{m.user.get_full_name() or m.user.email}'
            + (' (médico)' if Role.DOCTOR in (m.roles or []) else '')
        )
        self._estilizar()

    def clean_cpf(self):
        return ''.join(c for c in (self.cleaned_data.get('cpf') or '') if c.isdigit())

    def clean_cbo(self):
        # "2251.12", como aparece em muito sistema, vira 225112.
        return ''.join(c for c in (self.cleaned_data.get('cbo') or '') if c.isdigit())

    def clean(self):
        # Conferido aqui porque a restrição do banco inclui `tenant`, que
        # não é campo do formulário — o Django a pularia, e a duplicidade só
        # apareceria no INSERT, como erro 500.
        dados = super().clean()
        repetido = ProfissionalTiss.objects.filter(
            tenant_id=self.instance.tenant_id, conselho=dados.get('conselho'),
            numero_conselho=(dados.get('numero_conselho') or '').strip(), uf=dados.get('uf'),
        ).exclude(id=self.instance.id).exists()
        if repetido:
            self.add_error(
                'numero_conselho',
                'Já existe um profissional com este conselho, número e UF nesta clínica.',
            )
        return dados
