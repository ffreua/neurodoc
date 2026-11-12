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
from django.utils.html import format_html, format_html_join

from .estrutura import (
    A_COMPLETAR, ANESTESIA, CARATER, CATEGORIAS, EQUIPE_ANESTESIA, FORNECEDORES_SUGERIDOS,
    LATERALIDADE, MAX_NOME, MAX_TEXTO_CURTO, MAX_TEXTO_LONGO, QUANTIDADE_DE_FORNECEDORES, REGIME,
    ConteudoInvalido,
)

AJUDA_EXAMES = ('Um exame por linha. O código TUSS, se houver, no começo da linha: '
                '"40304361 HEMOGRAMA COMPLETO".')
AJUDA_PROCEDIMENTOS = ('Um procedimento por linha, com o código TUSS no começo e, se mais '
                       'de um, a quantidade no fim: "30715016 ARTRODESE DE COLUNA x2".')
AJUDA_MATERIAIS = ('Um material por linha, com a quantidade no começo: '
                   '"4 x PARAFUSO PEDICULAR 6,5 x 45 mm".')
AJUDA_LISTA = 'Um item por linha.'
AJUDA_CIDS = ('Um por linha, "código — descrição". Aparecem para escolher na emissão, '
              'ao lado das hipóteses do atendimento.')

#: As caixas de lista que `static/modelos/linhas.js` mostra como linhas,
#: cada uma com a caixa de quantidade e o botão de tirar. A caixa de texto
#: continua sendo o que vai no envio: sem o script, ela funciona como antes.
LINHAS_PROCEDIMENTO = {'data-nd-linhas': 'procedimento'}
LINHAS_MATERIAL = {'data-nd-linhas': 'material'}
LINHAS_LISTA = {'data-nd-linhas': 'lista'}


class CampoComSugestoes(forms.TextInput):
    """Campo livre com uma lista de sugestões (`<datalist>`).

    O fornecedor de OPME é sugerido e não escolhido: o cirurgião indica a
    empresa que quiser, e a lista só poupa a digitação das de sempre.
    """

    def __init__(self, sugestoes=(), attrs=None):
        super().__init__(attrs)
        self.sugestoes = tuple(sugestoes)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {})
        lista = f"{attrs.get('id') or name}-sugestoes"
        attrs['list'] = lista
        attrs.setdefault('autocomplete', 'off')
        campo = super().render(name, value, attrs, renderer)
        opcoes = format_html_join('', '<option value="{}"></option>', ((s,) for s in self.sugestoes))
        return format_html('{}<datalist id="{}">{}</datalist>', campo, lista, opcoes)


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
        label='CID no documento', required=False,
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


def _fornecedor(numero):
    return forms.CharField(
        label=f'Fornecedor de OPME {numero}', required=False, max_length=120,
        widget=CampoComSugestoes(FORNECEDORES_SUGERIDOS),
        help_text='O convênio cota o material com três empresas.' if numero == 1 else '',
    )


def _unidades(rotulo):
    return forms.IntegerField(label=rotulo, required=False, min_value=0, max_value=50,
                              help_text='Unidades. Vazio ou zero: não reservar.')


class SecaoCirurgiaForm(SecaoForm):
    """A solicitação de cirurgia, na ordem do guia do Dr. Fernando Freua
    (2026-11-12): a justificativa (história, exame, neuroimagem), o CID, os
    códigos, o OPME com os três fornecedores, a monitorização, os materiais
    do hospital, os hemocomponentes e a logística da internação.

    A reserva de hemoderivados deixou de ser uma caixa: ela é dita pelas
    unidades de cada hemocomponente, que é o que o banco de sangue pede.
    """

    tipo = estrutura.CIRURGIA
    indicacao = forms.CharField(
        label='Justificativa (história, exame neurológico e neuroimagem)',
        max_length=MAX_TEXTO_CURTO, widget=_area(6),
        help_text=f'Substitua cada {A_COMPLETAR} pelo que é deste paciente.',
    )
    cid = _cid()
    procedimentos = forms.CharField(label='Códigos (procedimentos)',
                                    widget=_area(5, **ALVO_TUSS, **LINHAS_PROCEDIMENTO),
                                    help_text=AJUDA_PROCEDIMENTOS)
    materiais = forms.CharField(label='Materiais de OPME', required=False,
                                widget=_area(6, **LINHAS_MATERIAL), help_text=AJUDA_MATERIAIS)
    fornecedor_1 = _fornecedor(1)
    fornecedor_2 = _fornecedor(2)
    fornecedor_3 = _fornecedor(3)
    monitorizacao = forms.BooleanField(label='Monitorização neurofisiológica intraoperatória',
                                       required=False)
    materiais_hospitalares = forms.CharField(
        label='Materiais hospitalares', required=False,
        widget=_area(4, **LINHAS_LISTA), help_text=AJUDA_LISTA,
    )
    hemo_ch = _unidades('Concentrado de hemácias (CH)')
    hemo_plasma = _unidades('Plasma')
    hemo_plaquetas = _unidades('Plaquetas')
    carater = forms.ChoiceField(label='Caráter', choices=CARATER, initial='eletiva')
    regime = forms.ChoiceField(label='Regime', choices=REGIME, initial='internacao')
    anestesia = forms.ChoiceField(label='Anestesia', choices=ANESTESIA, required=False)
    equipe_anestesia = forms.ChoiceField(label='Equipe de anestesia', choices=EQUIPE_ANESTESIA,
                                         required=False)
    lateralidade = forms.ChoiceField(label='Lateralidade', choices=LATERALIDADE, required=False)
    tempo_sala = forms.IntegerField(label='Tempo total de sala (minutos)', required=False,
                                    min_value=0, max_value=1440)
    uti = forms.BooleanField(label='UTI no pós-operatório', required=False)
    dias_uti = forms.IntegerField(label='Dias de UTI', required=False, min_value=0, max_value=365)
    dias_internacao = forms.IntegerField(label='Tempo total de internação (dias)', required=False,
                                         min_value=0, max_value=365)
    local = forms.CharField(label='Hospital / local', required=False, max_length=255)
    observacoes = forms.CharField(label='Observações', required=False,
                                  max_length=MAX_TEXTO_CURTO, widget=_area(2))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Os CIDs do modelo entram na escolha ao lado das hipóteses do
        # atendimento — separados, para o cirurgião ver de onde veio cada um.
        hipoteses = [c for c in self.fields['cid'].choices if c[0]]
        ja = {c[0] for c in hipoteses}
        do_modelo = [(c, c) for c in (self.initial.get('cids') or []) if c not in ja]
        escolhas = [('', 'Não incluir CID no documento')]
        if hipoteses:
            escolhas.append(('Hipóteses deste atendimento', hipoteses))
        if do_modelo:
            escolhas.append(('CIDs compatíveis do modelo', do_modelo))
        self.fields['cid'].choices = escolhas
        self.fields['cid'].help_text = 'O CID só sai impresso se você escolher.'

    def clean_indicacao(self):
        texto = self.cleaned_data.get('indicacao') or ''
        if A_COMPLETAR in texto:
            raise forms.ValidationError(
                f'Ainda há trechos {A_COMPLETAR} na justificativa. Escreva o que é deste paciente.'
            )
        return texto

    def clean_materiais_hospitalares(self):
        return _ler(estrutura.ler_lista, self.cleaned_data.get('materiais_hospitalares'))

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
                if nome == 'indicacao':
                    novo.label = 'Justificativa padrão'
                    novo.help_text = (f'Vem preenchida na emissão. Marque com {A_COMPLETAR} o que '
                                      'o cirurgião precisa escrever para cada caso.')
                    # Os CIDs logo depois da justificativa, como na emissão.
                    self.fields['cids'] = forms.CharField(
                        label='CIDs compatíveis', required=False,
                        widget=_area(5, **LINHAS_LISTA), help_text=AJUDA_CIDS,
                    )
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
            conteudo['fornecedores'] = [
                conteudo.pop(f'fornecedor_{n}', None) or ''
                for n in range(1, QUANTIDADE_DE_FORNECEDORES + 1)
            ]
            for campo, funcao in (('procedimentos', estrutura.ler_procedimentos),
                                  ('materiais', estrutura.ler_materiais),
                                  ('materiais_hospitalares', estrutura.ler_lista),
                                  ('cids', estrutura.ler_lista)):
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
        iniciais.update(iniciais_da_cirurgia(conteudo))
        iniciais['cids'] = '\n'.join(conteudo.get('cids') or [])
    else:
        iniciais.update(conteudo)
    return iniciais


def iniciais_da_cirurgia(conteudo):
    """O conteúdo da solicitação de cirurgia como valores iniciais dos campos.

    Uma função só para o editor do modelo e para a emissão: as listas viram
    texto de uma linha por item, e os fornecedores, os três campos.
    """
    iniciais = {k: v for k, v in conteudo.items()
                if k not in ('procedimentos', 'materiais', 'materiais_hospitalares', 'fornecedores')}
    iniciais['procedimentos'] = estrutura.texto_dos_procedimentos(conteudo.get('procedimentos'))
    iniciais['materiais'] = estrutura.texto_dos_materiais(conteudo.get('materiais'))
    iniciais['materiais_hospitalares'] = '\n'.join(conteudo.get('materiais_hospitalares') or [])
    fornecedores = list(conteudo.get('fornecedores') or [])
    for n in range(1, QUANTIDADE_DE_FORNECEDORES + 1):
        iniciais[f'fornecedor_{n}'] = fornecedores[n - 1] if len(fornecedores) >= n else ''
    for campo in ('dias_internacao', 'tempo_sala', 'dias_uti', 'hemo_ch', 'hemo_plasma',
                  'hemo_plaquetas'):
        iniciais[campo] = conteudo.get(campo) or None
    return iniciais
