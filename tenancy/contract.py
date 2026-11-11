"""O contrato de adesão, versionado, e os documentos que o integram.

**Redação de advogada.** O texto é o da Dra. Karina Albuquerque Freua,
OAB/SP nº 450.476, contratada para redigir e responder pela minuta. Não é
paráfrase nem adaptação. Quem for mexer aqui mexe num documento jurídico —
correção de redação passa por ela, não pelo código.

**Desde a 2.0, o documento dela é o arquivo**, e não uma transcrição:
`tenancy/contrato/contrato-<VERSAO>.md`, como ela o entregou, lido aqui e
renderizado na tela, no e-mail e no console. Até a 1.2 as cláusulas eram
copiadas item a item para listas em Python; com a 2.0 — vinte cláusulas,
cinco anexos com tabelas e o aviso de privacidade, uns 50 mil caracteres —
transcrever à mão seria o lugar mais provável de uma vírgula dela sumir. O
que este módulo faz com o arquivo é só **ler**: título, parágrafo, tabela e
o negrito que ela marcou. Nada é reescrito; a única alteração feita no
arquivo entregue foi o número da versão (ver `VERSAO`).

Continua no repositório, e não num PDF solto, pelo mesmo motivo de
sempre: o que a clínica aceitou precisa ser **conferível**.
`ContractAcceptance` guarda a versão, o SHA-256 de `texto_simples()` e a
cópia integral do texto aceito; um roteiro consegue afirmar que a tela, o
e-mail e o console mostram o mesmo documento.

**Versionamento.** `VERSAO` muda quando o texto muda, e nunca se edita uma
versão já aceita: texto novo é versão nova. Quem aceitou a 1.0, a 1.1 ou a
1.2 continua com a cópia arquivada no próprio aceite; a redação da 1.2
também está em `tenancy/contrato/contrato-1.2.txt`, gerada pelo código que
a servia, com o mesmo SHA-256 dos aceites dela.

**Por que o hash não está dentro do texto.** Ele não pode ser calculado
sobre um texto que já o contenha — o resultado mudaria o insumo. É
calculado sobre `texto_simples()` e apresentado ao lado dele, na tela, no
e-mail e no console.
"""
import re
from pathlib import Path

from django.utils.html import escape
from django.utils.safestring import mark_safe

#: Identificador da versão.
#:
#: **1.1** (2026-10-19): o item 16.3, sobre o código aberto sob a licença
#: MIT, autorizado pela Dra. Karina Albuquerque Freua.
#:
#: **1.2** (2026-10-29): muda só o CONTRATADO, que passa a ser a ProntDoc
#: Prontuários Médicos Ltda. — condição da numeração do SNCR. Autorizada
#: pela Dra. Karina Albuquerque Freua; as cláusulas não mudam uma palavra.
#:
#: **2.0** (2026-11-10): a redação revisada pela Dra. Karina, com
#: quadro-resumo, vinte cláusulas e, pela primeira vez, os documentos que a
#: 1.x anunciava como "ainda não disponibilizados" — Anexos I a V e o Aviso
#: de Privacidade. **O arquivo entregue dizia "Versão 2.2"**: era a
#: numeração das minutas dela, e a última versão publicada aqui era a 1.2.
#: Publicá-la como 2.2 deixaria uma 2.0 e uma 2.1 que nenhuma clínica
#: jamais viu, e o número de um contrato é o que se cita numa discussão.
#: Maior, e não 1.3, porque a redação inteira mudou. O número foi trocado
#: nas duas linhas do arquivo que o trazem, e em nada mais.
VERSAO = '2.0'

#: Início da vigência desta redação, no formato ISO.
VIGENCIA_DESDE = '2026-11-10'

ARQUIVO = Path(__file__).resolve().parent / 'contrato' / f'contrato-{VERSAO}.md'

#: A CONTRATADA, para quem a cita fora do contrato — o rodapé público e o
#: JSON-LD (`base/context_processors.py`, `base/seo.py`). O mesmo CNPJ que a
#: instalação informa à Anvisa no SNCR. `check_contrato` confere que o
#: documento da advogada diz o mesmo nome, CNPJ e endereço.
CONTRATADO = {
    'nome': 'ProntDoc Prontuários Médicos Ltda.',
    'qualificacao': 'pessoa jurídica de direito privado',
    'cnpj': '69.887.146/0001-05',
    'endereco': 'Avenida Paulista, nº 2073, sala 2220, São Paulo/SP',
    'papel': 'mantenedora da plataforma de software denominada NeuroDoc',
}

#: Quem respondeu pela redação. Fica no documento, e não só no histórico do
#: repositório: quem lê o contrato tem o direito de saber quem o redigiu. O
#: arquivo dela não traz o próprio nome, e por isso o bloco é acrescentado
#: ao fim — na tela, no texto puro e, portanto, no que o hash cobre.
REVISAO_JURIDICA = {
    'nome': 'Dra. Karina Albuquerque Freua',
    'oab': 'OAB/SP nº 450.476',
    'papel': 'Advogada responsável pela redação e pela revisão jurídica desta versão.',
}

_NEGRITO = re.compile(r'\*\*(.+?)\*\*')
_NUMERO = re.compile(r'^(\d+(?:\.\d+)+\.)\s+')
_CLAUSULA = re.compile(r'^CLÁUSULA (\d+) — (.+)$')
_ROMANO = re.compile(r'^ANEXO ([IVXL]+)\b')


def _simples(texto):
    return _NEGRITO.sub(r'\1', texto)


def _html(texto, numerar=False):
    """O parágrafo em HTML: escapado primeiro, e só então o negrito dela.

    `numerar` destaca o "1.1." do começo do item, como a tela fazia na 1.x.
    """
    corpo = escape(texto)
    prefixo = ''
    if numerar:
        achado = _NUMERO.match(corpo)
        if achado:
            prefixo = f'<span class="nd-contrato-numero">{achado.group(1)}</span>'
            corpo = corpo[achado.end():]
    return mark_safe(prefixo + _NEGRITO.sub(r'<strong>\1</strong>', corpo))


def _ancora(titulo, primeiro):
    if primeiro:
        return 'contrato'
    romano = _ROMANO.match(titulo)
    if romano:
        return f'anexo-{romano.group(1).lower()}'
    return re.sub(r'[^a-z0-9]+', '-', _simples(titulo).lower().split(' — ')[0]
                  .translate(str.maketrans('áâãàéêíóôõúç', 'aaaaeeiooouc'))).strip('-')


def _celulas(linha):
    return [c.strip() for c in linha.strip().strip('|').split('|')]


def ler(caminho=ARQUIVO):
    """Os documentos do arquivo, na ordem: o contrato, os anexos e o aviso.

    Cada um é `{'titulo', 'ancora', 'blocos'}`, e cada bloco é um título
    (`'h'`), um parágrafo (`'p'`) ou uma tabela (`'tabela'`), com o texto
    puro e o HTML lado a lado. **Estrito**: o que o leitor não reconhece
    levanta `ValueError`, em vez de sumir da tela calado.
    """
    documentos, tabela = [], None

    def fechar_tabela():
        nonlocal tabela
        if tabela is not None:
            documentos[-1]['blocos'].append(tabela)
            tabela = None

    for numero, linha in enumerate(Path(caminho).read_text(encoding='utf-8').splitlines(), start=1):
        linha = linha.rstrip()
        if linha.startswith('|'):
            celulas = _celulas(linha)
            if tabela is None:
                tabela = {'tipo': 'tabela', 'cabecalho': celulas, 'linhas': []}
            elif all(set(c) <= set('-: ') for c in celulas):
                continue
            else:
                if len(celulas) != len(tabela['cabecalho']):
                    raise ValueError(f'Linha {numero}: a tabela muda de número de colunas.')
                tabela['linhas'].append(celulas)
            continue
        fechar_tabela()
        if not linha or linha == '---':
            continue
        if linha.startswith('# '):
            titulo = linha[2:].strip()
            documentos.append({
                'titulo': titulo, 'ancora': _ancora(titulo, not documentos), 'blocos': [],
            })
            continue
        if not documentos:
            raise ValueError(f'Linha {numero}: texto antes do primeiro título.')
        if linha.startswith('## '):
            texto = linha[3:].strip()
            documentos[-1]['blocos'].append({'tipo': 'h', 'texto': texto, 'html': _html(texto)})
        elif linha.startswith('#'):
            raise ValueError(f'Linha {numero}: nível de título que o contrato não usa.')
        else:
            documentos[-1]['blocos'].append({
                'tipo': 'p', 'texto': _simples(linha), 'html': _html(linha, numerar=True),
            })
    fechar_tabela()

    for documento in documentos:
        for bloco in documento['blocos']:
            if bloco['tipo'] == 'tabela':
                bloco['cabecalho_html'] = [_html(c) for c in bloco['cabecalho']]
                bloco['linhas_html'] = [[_html(c) for c in linha] for linha in bloco['linhas']]
    return documentos


DOCUMENTOS = ler()

#: O título como ela o escreveu.
TITULO = DOCUMENTOS[0]['titulo']

#: Os documentos integrantes — o índice do alto da página, com o endereço
#: de cada um. Na 1.x esta lista dizia "ainda não disponibilizado" ao lado
#: de cada nome; desde a 2.0 todos estão no mesmo documento aceito.
ANEXOS = [(d['titulo'], d['ancora']) for d in DOCUMENTOS[1:]]


def _clausulas():
    """As cláusulas do contrato, para o roteiro e para quem precisar citá-las.

    O número é **o dela**, lido do título, e não a posição: com a redação no
    arquivo, a numeração passou a ser texto da advogada. `check_contrato`
    cobra que títulos e itens estejam em sequência.
    """
    saida = []
    for bloco in DOCUMENTOS[0]['blocos']:
        if bloco['tipo'] == 'h':
            achado = _CLAUSULA.match(bloco['texto'])
            if achado:
                saida.append({'numero': int(achado.group(1)), 'titulo': achado.group(2), 'itens': []})
            elif saida:
                break
        elif bloco['tipo'] == 'p' and saida and _NUMERO.match(bloco['texto']):
            saida[-1]['itens'].append(bloco['texto'])
    return saida


CLAUSULAS = _clausulas()

#: A declaração que o aceite registra, como ela a escreveu.
DECLARACAO_ACEITE = next(
    b['texto'] for b in DOCUMENTOS[0]['blocos']
    if b['tipo'] == 'p' and b['texto'].startswith('DECLARAÇÃO DE ACEITE')
)


def texto_simples():
    """O contrato inteiro em texto puro, para o e-mail e para a cópia arquivada.

    Inteiro quer dizer **com os anexos e o aviso**: a declaração de aceite
    diz "ter recebido o contrato e seus anexos integrais", e a cópia que a
    cláusula 2.2 manda conservar é a da "versão integral aceita". Gerado do
    mesmo arquivo que a tela renderiza; o SHA-256 é calculado sobre o que
    esta função devolve.

    A tabela vira uma linha por registro, com o nome de cada coluna: num
    e-mail de texto puro, colunas alinhadas a espaço se desfazem no
    primeiro leitor de fonte proporcional.
    """
    linhas = [f'Versão: {VERSAO}', f'Data de vigência: {VIGENCIA_DESDE}', '']
    for indice, documento in enumerate(DOCUMENTOS):
        if indice:
            linhas += ['=' * 70, '']
        linhas += [documento['titulo'], '']
        for bloco in documento['blocos']:
            if bloco['tipo'] == 'h':
                linhas += [bloco['texto'], '']
            elif bloco['tipo'] == 'p':
                linhas += [bloco['texto'], '']
            else:
                cabecalho = [_simples(c) for c in bloco['cabecalho']]
                for linha in bloco['linhas']:
                    pares = [f'{c}: {_simples(v)}' for c, v in zip(cabecalho, linha)]
                    linhas += ['- ' + ' | '.join(pares)]
                linhas += ['']
    linhas += [
        '=' * 70,
        '',
        'REVISÃO JURÍDICA',
        '',
        REVISAO_JURIDICA['nome'],
        REVISAO_JURIDICA['oab'],
        REVISAO_JURIDICA['papel'],
        '',
    ]
    return '\n'.join(linhas)
