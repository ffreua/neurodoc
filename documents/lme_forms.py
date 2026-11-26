"""O formulário da LME, campo a campo como o modelo do Ministério.

Os rótulos levam o número do item do modelo ("3 — Nome completo do
paciente"), para o médico achar no papel o que preencheu na tela. A
conferência de verdade é `lme.validar`, a mesma que a criação do rascunho
roda: o formulário só a chama e põe cada recusa no campo dela.
"""

from django import forms

from . import lme

MEDICAMENTOS = range(1, lme.MAX_MEDICAMENTOS + 1)
MESES = range(1, lme.MESES + 1)


def _texto(rotulo, maximo=255, obrigatorio=False, **attrs):
    return forms.CharField(label=rotulo, max_length=maximo, required=obrigatorio,
                           widget=forms.TextInput(attrs=attrs))


class LmeForm(forms.Form):
    cnes = _texto('1 — Número do CNES', 7, inputmode='numeric', autocomplete='off')
    estabelecimento = _texto('2 — Nome do estabelecimento de saúde solicitante', 150)
    paciente = _texto('3 — Nome completo do paciente', 150)
    mae = _texto('4 — Nome da mãe do paciente', 150)
    peso = _texto('5 — Peso (kg)', 6, inputmode='decimal')
    altura = _texto('6 — Altura (cm)', 3, inputmode='numeric')
    cid = _texto('9 — CID-10', 5, autocomplete='off')
    diagnostico = _texto('10 — Diagnóstico', 150)
    anamnese = forms.CharField(
        label='11 — Anamnese', max_length=2000, required=False,
        widget=forms.Textarea(attrs={'rows': 5}),
        help_text='O campo do formulário é pequeno: a letra diminui até caber, e o que não couber é recusado.',
    )
    tratamento_previo = forms.ChoiceField(
        label='12 — Paciente realizou tratamento prévio ou está em tratamento da doença?',
        choices=[('', '—')] + lme.SIM_NAO, required=False,
    )
    tratamento_relato = _texto('12 — Relato do tratamento prévio', 200)
    incapaz = forms.ChoiceField(
        label='13 — Atestado de capacidade: o paciente é considerado incapaz?',
        choices=[('', '—')] + lme.SIM_NAO, required=False,
        help_text='Se sim, indique o responsável, que poderá realizar a solicitação do medicamento.',
    )
    responsavel = _texto('13 — Nome do responsável', 150)
    medico = _texto('14 — Nome do médico solicitante', 150)
    medico_cns = _texto('15 — CNS do médico solicitante', 18, inputmode='numeric', autocomplete='off')
    preenchido_por = forms.ChoiceField(
        label='18 — Campos 19 a 23 preenchidos por', choices=lme.PREENCHIDO_POR, required=False,
    )
    preenchido_outro_nome = _texto('18 — Outro: nome', 150)
    preenchido_outro_cpf = _texto('18 — Outro: CPF', 14, inputmode='numeric')
    raca = forms.ChoiceField(
        label='19 — Raça/cor/etnia informada pelo paciente ou responsável',
        choices=[('', '—')] + lme.RACAS, required=False,
    )
    etnia = _texto('19 — Etnia (indígena)', 100)
    telefone1 = _texto('20 — Telefone para contato', 20, inputmode='tel')
    telefone2 = _texto('20 — Outro telefone', 20, inputmode='tel')
    documento_tipo = forms.ChoiceField(label='21 — Documento do paciente', choices=lme.DOCUMENTOS, required=False)
    documento_numero = _texto('21 — Número do documento', 20, inputmode='numeric')
    email = _texto('22 — E-mail do paciente', 150, inputmode='email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for n in MEDICAMENTOS:
            self.fields[f'med_{n}_nome'] = forms.CharField(
                label=f'Medicamento {n}', max_length=250, required=False,
                widget=forms.TextInput(attrs={'list': 'nd-lme-medicamentos', 'autocomplete': 'off'}),
            )
            for m in MESES:
                self.fields[f'med_{n}_q{m}'] = forms.CharField(
                    label=f'Medicamento {n}, {m}º mês', max_length=4, required=False,
                    widget=forms.TextInput(attrs={'inputmode': 'numeric', 'class': 'text-center'}),
                )
        inicial = self.initial or {}
        for n, item in enumerate(inicial.get('medicamentos') or [], start=1):
            if n > lme.MAX_MEDICAMENTOS:
                break
            self.initial[f'med_{n}_nome'] = item.get('nome', '')
            for m, q in enumerate(item.get('quantidades') or [], start=1):
                if m <= lme.MESES:
                    self.initial[f'med_{n}_q{m}'] = q

    def linhas_de_medicamento(self):
        """Para o template: uma linha por medicamento, com os seis meses."""
        return [
            {'n': n, 'nome': self[f'med_{n}_nome'], 'meses': [self[f'med_{n}_q{m}'] for m in MESES]}
            for n in MEDICAMENTOS
        ]

    def conteudo(self):
        """O conteúdo do documento, a partir dos dados limpos."""
        d = self.cleaned_data
        medicamentos = []
        for n in MEDICAMENTOS:
            nome = ' '.join((d.get(f'med_{n}_nome') or '').split())
            quantidades = [lme.so_digitos(d.get(f'med_{n}_q{m}')) if (d.get(f'med_{n}_q{m}') or '').strip()
                           else '' for m in MESES]
            # A quantidade que não é número fica como veio, para a
            # validação recusar em vez de sumir com ela.
            for i, m in enumerate(MESES):
                bruto = (d.get(f'med_{n}_q{m}') or '').strip()
                if bruto and not bruto.isdigit():
                    quantidades[i] = bruto
            if nome or any(quantidades):
                medicamentos.append({'nome': nome, 'quantidades': quantidades})
        conteudo = {chave: ' '.join(str(d.get(chave) or '').split()) for chave in lme.CAMPOS_DE_TEXTO
                    if chave not in ('anamnese', 'data')}
        conteudo['anamnese'] = (d.get('anamnese') or '').strip()
        conteudo['cnes'] = lme.so_digitos(d.get('cnes'))
        conteudo['cid'] = lme.normalizar_cid(d.get('cid'))
        conteudo['altura'] = lme.so_digitos(d.get('altura'))
        conteudo['peso'] = (d.get('peso') or '').strip().replace('.', ',')
        conteudo['medico_cns'] = lme.so_digitos(d.get('medico_cns'))
        for chave in lme.CAIXAS:
            conteudo[chave] = d.get(chave) or ''
        conteudo['medicamentos'] = medicamentos
        conteudo['modelo'] = lme.VERSAO_MODELO
        # Sem `data`: a do campo 16 é sempre a da emissão, posta no desenho
        # (`pdf/lme.py`), e não a do dia em que o rascunho foi escrito.
        return conteudo

    def clean(self):
        dados = super().clean()
        if self.errors:
            return dados
        try:
            lme.validar(self.conteudo())
        except lme.LmeInvalida as exc:
            for chave, mensagem in exc.erros.items():
                if chave.startswith('medicamento_'):
                    campo = f'med_{chave.split("_")[1]}_nome'
                elif chave in self.fields:
                    campo = chave
                else:
                    campo = None
                self.add_error(campo, mensagem)
        return dados
