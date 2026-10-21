"""A lista oficial das substâncias controladas (Anexo I da Portaria SVS/MS 344/1998).

**Por que existe.** Para saber que receituário um medicamento exige, o
NeuroDoc precisa da lista oficial — não da tarja da CMED. A tarja é dado
de preço (`catalogs/models.py::MedicationProduct`), não diz a lista, e o
FAQ da RDC 1.000/2025 (pergunta 68) proíbe dispensar controlado em receita
simples: errar a classificação devolve o paciente da farmácia. Decisão D7
de `docs/sncr/DECISOES.md`.

**De onde vem.** A Anvisa publica o Anexo I **inteiro** a cada atualização,
como texto da RDC no Anvisalegis (a página "Lista de substâncias sujeitas a
controle especial" aponta a vigente). O importador lê esse texto; o formato
é o mesmo há anos — "LISTA - C1", o título, o receituário entre parênteses,
os itens numerados e um "ADENDO:".

**O que este módulo decide, e o que não decide.**

- Decide a **lista** de cada substância e o **receituário** da lista, que é
  fixo em norma (`RECEITUARIO_POR_LISTA`).
- **Não** aplica os adendos. Eles trazem exceções por dose, forma
  farmacêutica, finalidade e associação ("os medicamentos à base de
  loperamida ficam sujeitos a venda sob prescrição sem retenção") — regra
  para ler, não para um programa adivinhar. O texto de cada adendo é
  guardado com a lista, e a tela o mostra ao médico; quem decide é ele.

**O parser é estrito de propósito.** Itens fora de sequência, lista sem
itens, ou uma das listas esperadas faltando derrubam a importação. Um
formato que mudou em silêncio importaria uma lista pela metade, e uma
lista pela metade diz "não controlado" para o que é.

Este módulo não importa Django: o parser roda e se confere isolado.
"""

import html
import re
import unicodedata
from dataclasses import dataclass, field

URL_PADRAO = (
    'https://anvisalegis.datalegis.net/action/ActionDatalegis.php?acao=abrirTextoAto'
    '&tipo=RDC&numeroAto=00001036&seqAto=000&valorAno=2026&orgao=RDC/DC/ANVISA/MS'
    '&codTipo=&desItem=&desItemFim=&cod_menu=1696&cod_modulo=134&pesquisa=true'
)

#: O receituário de cada lista, como a Portaria 344 o fixa.
#:
#: Em código, e não lido do parêntese do texto: o parêntese é redação
#: ("Sujeitas à Receita de Controle Especial em duas vias") e muda de
#: grafia entre atualizações; o que ele significa não muda. O texto lido
#: fica guardado ao lado (`ListaControlada.receituario_texto`) para quem
#: quiser conferir.
RECEITUARIO_POR_LISTA = {
    'A1': 'notificacao_a', 'A2': 'notificacao_a', 'A3': 'notificacao_a',
    'B1': 'notificacao_b', 'B2': 'notificacao_b2',
    'C1': 'rce', 'C5': 'rce',
    'C2': 'notificacao_retinoide', 'C3': 'notificacao_talidomida',
    'D1': 'sem_retencao', 'D2': 'nao_medicamento',
    'E': 'proscrita', 'F1': 'proscrita', 'F2': 'proscrita', 'F3': 'proscrita', 'F4': 'proscrita',
}

LISTAS_ESPERADAS = tuple(RECEITUARIO_POR_LISTA)

_CABECALHO = re.compile(r'^LISTA\s*-?\s*"?([A-F]\d?)"?\s*(?:-\s*(.*))?$')
_ITEM = re.compile(r'^(\d+)\.\s*(.*)$')
_FIM = re.compile(r'^(ADENDO\s*:?)', re.IGNORECASE)
#: O que o Anvisalegis põe depois do ato — a data de publicação e o aviso
#: de que o texto não substitui o oficial. Não é do último adendo.
_RODAPE = re.compile(r'^(PUB D\.O\.U\.|Este texto n.o substitui)', re.IGNORECASE)


class ListaInvalida(Exception):
    """O texto não tem a forma que o parser conhece. A importação para."""


@dataclass
class Substancia:
    numero: int
    nome: str
    sinonimos: list = field(default_factory=list)


@dataclass
class Lista:
    codigo: str
    titulo: str = ''
    receituario_texto: str = ''
    substancias: list = field(default_factory=list)
    adendo: str = ''


def normalizar(texto):
    """Sem acento e em maiúsculas — a mesma forma de `catalogs.importers`."""
    decomposto = unicodedata.normalize('NFKD', texto or '')
    return ''.join(c for c in decomposto if not unicodedata.combining(c)).upper()


def texto_do_html(conteudo):
    """O texto do ato, uma linha por bloco, a partir do HTML do Anvisalegis."""
    if isinstance(conteudo, bytes):
        # O Anvisalegis responde em ISO-8859-1 (cabeçalho `charset`); UTF-8
        # primeiro, para o caso de um dia mudar.
        try:
            conteudo = conteudo.decode('utf-8')
        except UnicodeDecodeError:
            conteudo = conteudo.decode('latin-1')
    conteudo = re.sub(r'<script.*?</script>|<style.*?</style>', '', conteudo, flags=re.S | re.I)
    conteudo = html.unescape(re.sub(r'<[^>]+>', '\n', conteudo))
    conteudo = re.sub(r'[ \t\xa0]+', ' ', conteudo)
    return '\n'.join(linha.strip() for linha in conteudo.splitlines() if linha.strip())


def versao_do_ato(texto):
    """'RDC 1036/2026' e o número da atualização do anexo, quando achados."""
    rdc = re.search(
        r'RESOLUCAO DA DIRETORIA COLEGIADA[^\n]*?N\S{0,2}\s*([\d.]+),\s*DE\s*\d+\s*DE\s*\w+\s*DE\s*(\d{4})',
        normalizar(texto),
    )
    atualizacao = re.search(r'ATUALIZACAO\s*N\.?\s*(\d+)', normalizar(texto))
    nome = f'RDC {rdc.group(1).replace(".", "")}/{rdc.group(2)}' if rdc else ''
    return nome, (atualizacao.group(1) if atualizacao else '')


def _separar_nome(bruto):
    partes = [p.strip(' ;,') for p in re.split(r'\s+ou\s+', bruto) if p.strip(' ;,')]
    return (partes[0] if partes else ''), partes[1:]


def ler(texto):
    """As listas do Anexo I, na ordem do texto. Levanta `ListaInvalida`."""
    linhas = texto.splitlines()
    # O anexo começa no primeiro "LISTA - A1"; o que vem antes é o
    # preâmbulo da resolução, que também cita listas ("Lista "D1": ...").
    inicio = next((i for i, l in enumerate(linhas) if _CABECALHO.match(l) and 'A1' in l), None)
    if inicio is None:
        raise ListaInvalida('não achei o começo do anexo ("LISTA - A1")')

    listas, atual, item, no_adendo = [], None, None, False

    def fechar_item():
        nonlocal item
        if item is not None:
            nome, sinonimos = _separar_nome(' '.join(item[1]).strip())
            if not nome:
                raise ListaInvalida(f'lista {atual.codigo}: item {item[0]} sem nome')
            atual.substancias.append(Substancia(item[0], nome, sinonimos))
        item = None

    for linha in linhas[inicio:]:
        if _RODAPE.match(linha):
            break
        cab = _CABECALHO.match(linha)
        if cab and cab.group(1) in RECEITUARIO_POR_LISTA or (cab and cab.group(1) == 'F'):
            fechar_item()
            codigo = cab.group(1)
            if codigo == 'F':
                # "LISTA - F" é só o título das quatro sublistas (F1 a F4).
                atual, no_adendo = None, False
                continue
            atual = Lista(codigo=codigo, titulo=(cab.group(2) or '').strip())
            listas.append(atual)
            no_adendo = False
            continue
        if atual is None:
            continue
        if _FIM.match(linha):
            fechar_item()
            no_adendo = True
            continue
        if no_adendo:
            atual.adendo = (atual.adendo + '\n' + linha).strip()
            continue
        if linha.startswith('(') and not atual.substancias and item is None:
            atual.receituario_texto = linha.strip('()')
            continue
        m = _ITEM.match(linha)
        esperado = len(atual.substancias) + (2 if item is not None else 1)
        if m and int(m.group(1)) == esperado:
            fechar_item()
            item = (int(m.group(1)), [m.group(2)] if m.group(2) else [])
            continue
        if item is None:
            if not atual.substancias and not atual.receituario_texto:
                atual.titulo = (atual.titulo + ' ' + linha).strip()
            continue
        item[1].append(linha)
    fechar_item()

    codigos = [l.codigo for l in listas]
    faltando = [c for c in LISTAS_ESPERADAS if c not in codigos]
    if faltando:
        raise ListaInvalida(f'listas ausentes: {", ".join(faltando)}')
    repetidas = {c for c in codigos if codigos.count(c) > 1}
    if repetidas:
        raise ListaInvalida(f'listas repetidas: {", ".join(sorted(repetidas))}')
    for lista in listas:
        if not lista.substancias:
            raise ListaInvalida(f'lista {lista.codigo} sem nenhuma substância')
    return listas
