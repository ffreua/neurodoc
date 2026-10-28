"""Formulários de Modelos: a seção da tela de emissão e o editor do modelo.

As listas (exames, procedimentos, materiais) são caixas de texto com **uma
linha por item** — ver `modelos/estrutura.py`. A leitura das linhas é a
mesma no editor do modelo e na emissão, e o texto devolvido à tela sai da
mesma função que o escreve, para editar e salvar não mudar nada.
"""

import copy

from django import forms

from documents.pdf.prescription import FORMAT_CHOICES as FORMATOS_DE_RECEITA, SIMPLE

from . import estrutura
from .estrutura import (
    ANESTESIA, CARATER, CATEGORIAS, LATERALIDADE, MAX_NOME, MAX_TEXTO_CURTO, MAX_TEXTO_LONGO,
    REGIME, ConteudoInvalido,
)

AJUDA_EXAMES = ('Um exame por linha. O código TUSS, se houver, no começo da linha: '
                '"40304361 HEMOGRAMA COMPLETO".')
AJUDA_PROCEDIMENTOS = ('Um procedimento por linha, com o código TUSS no começo e, se mais '
                       'de um, a quantidade no fim: "30715016 ARTRODESE DE COLUNA x2".')
AJUDA_MATERIAIS = ('Um material por linha, com a quantidade no começo: '
                   '"4 x PARAFUSO PEDICULAR 6,5 x 45 mm".')


#: Marca a caixa onde a busca TUSS (`static/modelos/modelos.js`) insere o
#: código escolhido: a última dessas em que o cursor esteve.
ALVO_TUSS = {'data-nd-tuss-alvo': '1'}


def _area(linhas=4, **extra):
    return forms.Textarea(attrs={'rows': linhas, **extra})


def _ler(funcao, valor):
    try:
        return funcao(valor)
    except ConteudoInvalido as exc:
        raise forms.ValidationError(str(exc)) from exc


# ------------------------------------------------------- seções da emissão


class SecaoForm(forms.Form):
    """Base de uma seção da tela de emissão: um documento a sair.

    `emitir` existe para o conjunto — o médico desmarca o pedido de imagem
    que não quer agora e emite só o de laboratório. Seção desmarcada não é
    validada nem emitida.
    """

    emitir = forms.BooleanField(label='Emitir este documento', required=False, initial=True)

    def __init__(self, *args, diagnosticos=(), **kwargs):
        super().__init__(*args, **kwargs)
        if 'cid' in self.fields:
            self.fields['cid'].choices = [('', 'Não incluir CID no documento')] + [
                (d, d) for d in diagnosticos
            ]


def _cid():
    return forms.ChoiceField(
        label='CID-10 no documento', required=False,
        help_text='As hipóteses deste atendimento. O CID só sai impresso se você escolher.',
    )


class SecaoExamesForm(SecaoForm):
    tipo = estrutura.EXAMES
    categoria = forms.ChoiceField(
        choices=[(c.codigo, c.rotulo) for c in CATEGORIAS], widget=forms.HiddenInput,
    )
    itens = forms.CharField(label='Exames', widget=_area(10, **ALVO_TUSS), help_text=AJUDA_EXAMES)
    indicacao = forms.CharField(
        label='Indicação clínica / justificativa', required=False,
        max_length=MAX_TEXTO_CURTO, widget=_area(3),
    )
    cid = _cid()
    observacoes = forms.CharField(
        label='Observações', required=False, max_length=MAX_TEXTO_CURTO, widget=_area(2),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cat = estrutura.categoria(self.initial.get('categoria') or self.data.get(self.add_prefix('categoria')))
        if cat and cat.exige_indicacao:
            self.fields['indicacao'].required = True
            self.fields['indicacao'].help_text = (
                f'Obrigatória para {cat.rotulo.lower()}: o serviço protocola o exame pela '
                'pergunta clínica, e o convênio devolve a guia sem ela.'
            )

    def clean_itens(self):
        itens = _ler(estrutura.ler_exames, self.cleaned_data.get('itens'))
        if not itens:
            raise forms.ValidationError('Inclua ao menos um exame.')
        return itens


class SecaoCirurgiaForm(SecaoForm):
    tipo = estrutura.CIRURGIA
    procedimentos = forms.CharField(label='Procedimentos', widget=_area(5, **ALVO_TUSS),
                                    help_text=AJUDA_PROCEDIMENTOS)
    materiais = forms.CharField(label='Materiais e OPME', required=False, widget=_area(6),
                                help_text=AJUDA_MATERIAIS)
    indicacao = forms.CharField(label='Indicação clínica / justificativa',
                                max_length=MAX_TEXTO_CURTO, widget=_area(3))
    cid = _cid()
    carater = forms.ChoiceField(label='Caráter', choices=CARATER, initial='eletiva')
    regime = forms.ChoiceField(label='Regime', choices=REGIME, initial='internacao')
    dias_internacao = forms.IntegerField(label='Dias de internação previstos', required=False,
                                         min_value=0, max_value=365)
    anestesia = forms.ChoiceField(label='Anestesia', choices=ANESTESIA, required=False)
    lateralidade = forms.ChoiceField(label='Lateralidade', choices=LATERALIDADE, required=False)
    uti = forms.BooleanField(label='UTI no pós-operatório', required=False)
    reserva_sangue = forms.BooleanField(label='Reserva de hemoderivados', required=False)
    local = forms.CharField(label='Hospital / local', required=False, max_length=255)
    observacoes = forms.CharField(label='Observações', required=False,
                                  max_length=MAX_TEXTO_CURTO, widget=_area(2))

    def clean_procedimentos(self):
        itens = _ler(estrutura.ler_procedimentos, self.cleaned_data.get('procedimentos'))
        if not itens:
            raise forms.ValidationError('Inclua ao menos um procedimento.')
        return itens

    def clean_materiais(self):
        return _ler(estrutura.ler_materiais, self.cleaned_data.get('materiais'))


class SecaoRelatorioForm(SecaoForm):
    tipo = estrutura.RELATORIO
    texto = forms.CharField(label='Texto do relatório', max_length=MAX_TEXTO_LONGO, widget=_area(12))


class SecaoReceitaForm(SecaoForm):
    tipo = estrutura.RECEITA
    formato = forms.ChoiceField(label='Formato da receita', choices=FORMATOS_DE_RECEITA, initial=SIMPLE)
    texto = forms.CharField(label='Prescrição', max_length=MAX_TEXTO_LONGO, widget=_area(8))
    instrucoes = forms.CharField(label='Instruções especiais', required=False,
                                 max_length=MAX_TEXTO_CURTO, widget=_area(2))


FORM_DA_SECAO = {
    estrutura.EXAMES: SecaoExamesForm,
    estrutura.CIRURGIA: SecaoCirurgiaForm,
    estrutura.RELATORIO: SecaoRelatorioForm,
    estrutura.RECEITA: SecaoReceitaForm,
}


# ------------------------------------------------------- editor do modelo


class ModeloForm(forms.Form):
    """O editor do modelo do médico. Os campos dependem do tipo.

    O pedido de exames tem **uma caixa por categoria**: o modelo de uma
    categoria só preenche uma; o conjunto ("Queixa cognitiva") preenche
    mais de uma, e cada caixa preenchida vira um pedido na emissão.
    """

    nome = forms.CharField(label='Nome do modelo', max_length=MAX_NOME)

    def __init__(self, *args, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo = tipo
        if tipo == estrutura.EXAMES:
            for cat in CATEGORIAS:
                self.fields[f'grupo_{cat.codigo}'] = forms.CharField(
                    label=cat.rotulo, required=False, widget=_area(6, **ALVO_TUSS),
                    help_text=AJUDA_EXAMES,
                )
            self.fields['indicacao'] = forms.CharField(
                label='Indicação clínica padrão', required=False, max_length=MAX_TEXTO_CURTO,
                widget=_area(2), help_text='Vem preenchida na emissão, para você ajustar ao caso.',
            )
            self.fields['observacoes'] = forms.CharField(
                label='Observações padrão', required=False, max_length=MAX_TEXTO_CURTO, widget=_area(2),
            )
        elif tipo == estrutura.CIRURGIA:
            for nome, campo in SecaoCirurgiaForm.base_fields.items():
                if nome in ('emitir', 'cid'):
                    continue
                # Cópia do campo da seção, como o próprio Django copia
                # `base_fields` para cada formulário — e opcional: no modelo
                # tudo pode ficar para preencher na hora.
                novo = copy.deepcopy(campo)
                novo.required = False
                self.fields[nome] = novo
        elif tipo == estrutura.RELATORIO:
            self.fields['texto'] = forms.CharField(
                label='Texto do relatório', max_length=MAX_TEXTO_LONGO, widget=_area(12),
            )
        elif tipo == estrutura.RECEITA:
            self.fields['texto'] = forms.CharField(
                label='Prescrição', max_length=MAX_TEXTO_LONGO, widget=_area(8),
            )
            self.fields['instrucoes'] = forms.CharField(
                label='Instruções especiais', required=False, max_length=MAX_TEXTO_CURTO, widget=_area(2),
            )

    def clean(self):
        dados = super().clean()
        try:
            self.conteudo = estrutura.normalizar(self.tipo, self._conteudo(dados))
        except ConteudoInvalido as exc:
            raise forms.ValidationError(str(exc)) from exc
        if self.tipo == estrutura.EXAMES and not self.conteudo['grupos']:
            raise forms.ValidationError('Inclua ao menos um exame em alguma das categorias.')
        return dados

    def _conteudo(self, dados):
        if self.tipo == estrutura.EXAMES:
            grupos = {}
            for cat in CATEGORIAS:
                try:
                    grupos[cat.codigo] = estrutura.ler_exames(dados.get(f'grupo_{cat.codigo}'))
                except ConteudoInvalido as exc:
                    self.add_error(f'grupo_{cat.codigo}', str(exc))
            return {'grupos': grupos, 'indicacao': dados.get('indicacao'),
                    'observacoes': dados.get('observacoes')}
        if self.tipo == estrutura.CIRURGIA:
            conteudo = {k: dados.get(k) for k in self.fields if k != 'nome'}
            for campo, funcao in (('procedimentos', estrutura.ler_procedimentos),
                                  ('materiais', estrutura.ler_materiais)):
                try:
                    conteudo[campo] = funcao(dados.get(campo))
                except ConteudoInvalido as exc:
                    self.add_error(campo, str(exc))
                    conteudo[campo] = []
            return conteudo
        return {k: dados.get(k) for k in self.fields if k != 'nome'}


def valores_iniciais_do_editor(tipo, conteudo, nome=''):
    """O modelo gravado (ou do sistema) como valores iniciais do editor."""
    iniciais = {'nome': nome}
    if tipo == estrutura.EXAMES:
        for cat in CATEGORIAS:
            iniciais[f'grupo_{cat.codigo}'] = estrutura.texto_dos_exames(
                (conteudo.get('grupos') or {}).get(cat.codigo)
            )
        iniciais.update(indicacao=conteudo.get('indicacao', ''),
                        observacoes=conteudo.get('observacoes', ''))
    elif tipo == estrutura.CIRURGIA:
        iniciais.update({k: v for k, v in conteudo.items()
                         if k not in ('procedimentos', 'materiais')})
        iniciais['procedimentos'] = estrutura.texto_dos_procedimentos(conteudo.get('procedimentos'))
        iniciais['materiais'] = estrutura.texto_dos_materiais(conteudo.get('materiais'))
    else:
        iniciais.update(conteudo)
    return iniciais
