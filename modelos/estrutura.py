"""A forma do conteúdo de um modelo, e o que um modelo pode conter.

Um modelo é **texto pronto para editar**, nunca um documento: o que ele
carrega vai para a tela de emissão, o médico muda o que quiser, e só o que
sai dali vira documento (`modelos/emissao.py`). Por isso esta forma é
pensada para a tela — listas que se editam como linhas de texto — e não
para o PDF.

Quatro tipos, e cada um vira um tipo de documento já conhecido do sistema:

| Tipo do modelo | Documento (`MedicalDocumentKind`) |
| --- | --- |
| `exames` | `exam_request` — **um por categoria** |
| `cirurgia` | `surgery_request` |
| `relatorio` | `report` |
| `receita` | `prescription` (simples ou controle especial) |

**Pedido de exames tem categoria por grupo, e não por modelo.** "Queixa
cognitiva" pede uma ressonância e um painel de sangue: são dois pedidos —
o laboratório não recebe a ressonância e a clínica de imagem não recebe o
hemograma, e o convênio autoriza um e outro por guias diferentes. O modelo
guarda os itens agrupados (`grupos`), e a emissão abre **um pedido por
grupo**. Um modelo com um grupo só é um pedido; com mais de um, é um
conjunto, e a tela de Modelos o mostra na aba de conjuntos.

As listas são editadas como **uma linha por item**. É o editor mais
flexível que existe — copiar, colar, apagar uma linha — e não depende de
JavaScript para incluir ou remover item. O código TUSS, quando houver, vai
no começo da linha (`40304361 HEMOGRAMA COMPLETO`), e a leitura o separa
da descrição. Nunca há chave estrangeira para a TUSS: a sincronização
semanal apaga e recria as linhas da tabela, e o modelo guardaria um id que
deixa de existir (o mesmo cuidado do CID em `EncounterDiagnosis`).
"""

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- categorias


@dataclass(frozen=True)
class Categoria:
    codigo: str
    rotulo: str
    #: A indicação clínica é exigida na emissão. Para imagem ela é regra de
    #: convênio e de serviço de imagem: o radiologista protocola o exame
    #: pela pergunta clínica, e a guia sem justificativa volta.
    exige_indicacao: bool = False


#: A ordem é a das abas na tela de Modelos e dos grupos na Conduta.
CATEGORIAS = (
    Categoria('laboratorio', 'Laboratório (sangue e urina)'),
    Categoria('imagem', 'Imagem', exige_indicacao=True),
    Categoria('neurofisiologia', 'Neurofisiologia'),
    Categoria('liquor', 'Líquor'),
    Categoria('cardiologia', 'Cardiologia'),
    Categoria('sono', 'Sono'),
    Categoria('outros', 'Outros'),
)
CATEGORIA_POR_CODIGO = {c.codigo: c for c in CATEGORIAS}


def categoria(codigo):
    return CATEGORIA_POR_CODIGO.get(codigo)


# --------------------------------------------------------------------- tipos

EXAMES = 'exames'
CIRURGIA = 'cirurgia'
RELATORIO = 'relatorio'
RECEITA = 'receita'

TIPOS = (
    (EXAMES, 'Pedido de exames'),
    (RELATORIO, 'Relatório'),
    (CIRURGIA, 'Solicitação de cirurgia'),
    (RECEITA, 'Receita'),
)
ROTULO_DO_TIPO = dict(TIPOS)

# Opções da solicitação de cirurgia. Fixas em código: são o vocabulário da
# guia de internação, e texto livre aqui viraria dez grafias da mesma coisa.
CARATER = (('eletiva', 'Eletiva'), ('urgencia', 'Urgência'))
REGIME = (
    ('internacao', 'Internação'),
    ('hospital_dia', 'Hospital-dia'),
    ('ambulatorial', 'Ambulatorial'),
)
ANESTESIA = (
    ('', 'A definir pela anestesiologia'),
    ('geral', 'Geral'),
    ('raquidiana', 'Raquidiana'),
    ('peridural', 'Peridural'),
    ('sedacao', 'Sedação'),
    ('local', 'Local'),
    ('bloqueio', 'Bloqueio regional'),
)
LATERALIDADE = (
    ('', 'Não se aplica'),
    ('direita', 'Direita'),
    ('esquerda', 'Esquerda'),
    ('bilateral', 'Bilateral'),
)

# ------------------------------------------------------------------- limites
#
# Contra o envio que trava a tela e o PDF, não contra o uso: o maior modelo
# do sistema (Neuropatia) tem pouco mais de sessenta exames.
MAX_ITENS = 150
MAX_DESCRICAO = 300
MAX_TEXTO_CURTO = 4000
MAX_TEXTO_LONGO = 20000
MAX_NOME = 120

# --------------------------------------------------------------- as linhas

_CODIGO = re.compile(r'^(\d{8})\s*[-–—|·:]?\s*(.*)$')
_QTD_NO_FIM = re.compile(r'^(.*?)\s+[xX×]\s*(\d{1,3})$')
_QTD_NO_INICIO = re.compile(r'^(\d{1,3})\s*[xX×]\s+(.+)$')


class ConteudoInvalido(ValueError):
    """Conteúdo de modelo fora da forma. A mensagem vai para a tela."""


def _linhas(texto):
    return [linha.strip() for linha in (texto or '').splitlines() if linha.strip()]


def _conferir_descricao(descricao, numero):
    if len(descricao) > MAX_DESCRICAO:
        raise ConteudoInvalido(
            f'A linha {numero} passa de {MAX_DESCRICAO} caracteres. Divida em duas.'
        )


def _conferir_quantidade_de_itens(itens):
    if len(itens) > MAX_ITENS:
        raise ConteudoInvalido(f'São no máximo {MAX_ITENS} itens por lista.')


def ler_exames(texto):
    """Uma linha por exame: `[código TUSS] descrição`.

    Linhas repetidas (a mesma descrição, sem diferença de caixa) entram uma
    vez: o mesmo exame duas vezes no pedido vira duas cobranças na guia.
    """
    itens, vistos = [], set()
    for numero, linha in enumerate(_linhas(texto), start=1):
        codigo, descricao = '', linha
        achado = _CODIGO.match(linha)
        if achado and achado.group(2).strip():
            codigo, descricao = achado.group(1), achado.group(2).strip()
        _conferir_descricao(descricao, numero)
        chave = (codigo, descricao.casefold())
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append({'codigo': codigo, 'descricao': descricao})
    _conferir_quantidade_de_itens(itens)
    return itens


def texto_dos_exames(itens):
    return '\n'.join(
        f"{i['codigo']} {i['descricao']}" if i.get('codigo') else i['descricao']
        for i in itens or []
    )


def ler_procedimentos(texto):
    """Uma linha por procedimento: `[código TUSS] descrição [x quantidade]`."""
    itens = []
    for numero, linha in enumerate(_linhas(texto), start=1):
        quantidade = 1
        no_fim = _QTD_NO_FIM.match(linha)
        if no_fim:
            linha, quantidade = no_fim.group(1).strip(), int(no_fim.group(2))
        codigo, descricao = '', linha
        achado = _CODIGO.match(linha)
        if achado and achado.group(2).strip():
            codigo, descricao = achado.group(1), achado.group(2).strip()
        _conferir_descricao(descricao, numero)
        itens.append({'codigo': codigo, 'descricao': descricao, 'quantidade': max(quantidade, 1)})
    _conferir_quantidade_de_itens(itens)
    return itens


def texto_dos_procedimentos(itens):
    linhas = []
    for i in itens or []:
        linha = f"{i['codigo']} {i['descricao']}" if i.get('codigo') else i['descricao']
        if int(i.get('quantidade') or 1) > 1:
            linha += f" x{int(i['quantidade'])}"
        linhas.append(linha)
    return '\n'.join(linhas)


def ler_materiais(texto):
    """Uma linha por material: `[quantidade x] descrição`.

    O código (ANVISA, referência do fabricante, TUSS de OPME) fica dentro da
    descrição, como o cirurgião o escreve: cada fornecedor usa um, e um
    campo próprio obrigaria a escolher qual.
    """
    itens = []
    for numero, linha in enumerate(_linhas(texto), start=1):
        quantidade = 1
        no_inicio = _QTD_NO_INICIO.match(linha)
        if no_inicio:
            quantidade, linha = int(no_inicio.group(1)), no_inicio.group(2).strip()
        _conferir_descricao(linha, numero)
        itens.append({'descricao': linha, 'quantidade': max(quantidade, 1)})
    _conferir_quantidade_de_itens(itens)
    return itens


def texto_dos_materiais(itens):
    return '\n'.join(
        f"{int(i.get('quantidade') or 1)} x {i['descricao']}" for i in itens or []
    )


# --------------------------------------------------------- o modelo inteiro


def _texto(valor, limite, rotulo):
    valor = (valor or '').strip()
    if len(valor) > limite:
        raise ConteudoInvalido(f'{rotulo} passa de {limite} caracteres.')
    return valor


def _escolha(valor, opcoes, padrao=''):
    validos = {codigo for codigo, _ in opcoes}
    return valor if valor in validos else padrao


def normalizar(tipo, conteudo):
    """O conteúdo na forma canônica do tipo, ou `ConteudoInvalido`.

    Passa por aqui tudo que vai ser gravado — o modelo do médico e o do
    sistema, conferido pelo roteiro — para que a tela de emissão nunca
    encontre uma chave faltando ou um tipo trocado.
    """
    conteudo = conteudo or {}
    if tipo == EXAMES:
        grupos = {}
        for codigo, itens in (conteudo.get('grupos') or {}).items():
            if codigo not in CATEGORIA_POR_CODIGO:
                raise ConteudoInvalido(f'Categoria de exame desconhecida: {codigo}.')
            limpos = [
                {'codigo': (i.get('codigo') or '').strip(),
                 'descricao': _texto(i.get('descricao'), MAX_DESCRICAO, 'A descrição do exame')}
                for i in itens or [] if (i.get('descricao') or '').strip()
            ]
            _conferir_quantidade_de_itens(limpos)
            if limpos:
                grupos[codigo] = limpos
        return {
            # Na ordem das categorias, e não na ordem em que chegaram: é a
            # ordem em que os pedidos aparecem para emitir.
            'grupos': {c.codigo: grupos[c.codigo] for c in CATEGORIAS if c.codigo in grupos},
            'indicacao': _texto(conteudo.get('indicacao'), MAX_TEXTO_CURTO, 'A indicação'),
            'observacoes': _texto(conteudo.get('observacoes'), MAX_TEXTO_CURTO, 'As observações'),
        }
    if tipo == CIRURGIA:
        dias = str(conteudo.get('dias_internacao') or '').strip()
        if dias and (not dias.isdigit() or int(dias) > 365):
            raise ConteudoInvalido('Os dias de internação são um número de 0 a 365.')
        return {
            'procedimentos': [
                {'codigo': (p.get('codigo') or '').strip(),
                 'descricao': _texto(p.get('descricao'), MAX_DESCRICAO, 'O procedimento'),
                 'quantidade': max(int(p.get('quantidade') or 1), 1)}
                for p in conteudo.get('procedimentos') or [] if (p.get('descricao') or '').strip()
            ][:MAX_ITENS],
            'materiais': [
                {'descricao': _texto(m.get('descricao'), MAX_DESCRICAO, 'O material'),
                 'quantidade': max(int(m.get('quantidade') or 1), 1)}
                for m in conteudo.get('materiais') or [] if (m.get('descricao') or '').strip()
            ][:MAX_ITENS],
            'indicacao': _texto(conteudo.get('indicacao'), MAX_TEXTO_CURTO, 'A indicação'),
            'carater': _escolha(conteudo.get('carater'), CARATER, 'eletiva'),
            'regime': _escolha(conteudo.get('regime'), REGIME, 'internacao'),
            'dias_internacao': dias,
            'anestesia': _escolha(conteudo.get('anestesia'), ANESTESIA),
            'lateralidade': _escolha(conteudo.get('lateralidade'), LATERALIDADE),
            'uti': bool(conteudo.get('uti')),
            'reserva_sangue': bool(conteudo.get('reserva_sangue')),
            'local': _texto(conteudo.get('local'), 255, 'O local'),
            'observacoes': _texto(conteudo.get('observacoes'), MAX_TEXTO_CURTO, 'As observações'),
        }
    if tipo == RELATORIO:
        return {'texto': _texto(conteudo.get('texto'), MAX_TEXTO_LONGO, 'O texto')}
    if tipo == RECEITA:
        return {
            'texto': _texto(conteudo.get('texto'), MAX_TEXTO_LONGO, 'A prescrição'),
            'instrucoes': _texto(conteudo.get('instrucoes'), MAX_TEXTO_CURTO, 'As instruções'),
        }
    raise ConteudoInvalido(f'Tipo de modelo desconhecido: {tipo}.')


def categorias_do_modelo(tipo, conteudo):
    """As categorias de exame que o modelo pede, na ordem das abas."""
    if tipo != EXAMES:
        return []
    return [c for c in CATEGORIAS if (conteudo.get('grupos') or {}).get(c.codigo)]


def eh_conjunto(tipo, conteudo):
    return len(categorias_do_modelo(tipo, conteudo)) > 1
