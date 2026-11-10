"""CID-10 e CID-11 lado a lado (1.44): qual é qual, e a carga da CID-11.

## Por que as duas, e por que a CID-10 continua na frente

A CID-11 é a revisão em vigor da OMS, e o médico que publica, que atende
paciente de fora ou que já pensa pela classificação nova quer registrar o
código dela. A CID-10 continua sendo a padrão da tela porque é a que os
papéis brasileiros pedem hoje — atestado, guia de convênio, sistemas
oficiais. Trocar uma pela outra tiraria do prontuário o código que o
papel exige; ter as duas não tira nada de ninguém.

## Por que não há coluna dizendo de qual classificação é o código

A alternativa — um campo `sistema` em `EncounterDiagnosis` — foi recusada.
O código já diz de qual é, e foi a OMS que o desenhou assim: na CID-11 **a
segunda posição é sempre uma letra** (`8A00`, `BA00.1`), na CID-10 é
sempre um número (`G20`, `G40.2`). Uma coluna a mais teria de ser
carregada pela cópia da consulta anterior, pela IA, pela exportação, pelos
modelos de documento e pela migração do iClin — e o primeiro caminho que a
esquecesse gravaria `8A00` como CID-10. Lida do próprio código, a resposta
não tem como divergir dele, e vale também para o código digitado à mão.

## O que entra da CID-11

Os códigos-tronco dos capítulos 1 a 25 — doenças, sintomas, causas
externas e fatores de contato com o serviço. Ficam fora, de propósito:

- **capítulo X (códigos de extensão)**: 16.858 códigos que não valem
  sozinhos — só acompanham um código-tronco, num agrupamento que esta tela
  não monta. Oferecê-los na busca de hipótese convidaria a gravar
  "direita" como diagnóstico;
- **capítulo 26 (medicina tradicional) e seção V (funcionalidade)**:
  suplementares, e na busca apareceriam como "cefaleia (MT1)" ao lado da
  cefaleia do capítulo 8.

O **agrupamento** (pós-coordenação, `8A00.0&XK9J`) também não é montado:
quem precisar escreve o código à mão, que o campo aceita.

## A planilha é a da OMS, sem tocar

`catalogs/data/SimpleTabulation-ICD-11-MMS-pt.xlsx` é o arquivo como foi
baixado de icd.who.int, conferido por SHA-256 antes de ser lido. A CID-11
é publicada sob **CC BY-ND 3.0 IGO**: pode ser redistribuída com a
atribuição, e não pode ser alterada. Por isso o repositório guarda o
original e não um CSV derivado dele, e a leitura abaixo não corrige
título nem código — só tira os traços de indentação que a planilha põe na
frente do título para desenhar a hierarquia. Onde a tradução da OMS ainda
não chegou (671 categorias residuais), o título fica em inglês, como veio.
"""
import hashlib
import logging
import re
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from .models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, DiagnosisCode

logger = logging.getLogger(__name__)

CID10 = CatalogSystem.CID10.value
CID11 = CatalogSystem.CID11.value

ROTULOS = {CID10: 'CID-10', CID11: 'CID-11'}

DATA_DIR = Path(__file__).resolve().parent / 'data'
CID11_ARQUIVO = DATA_DIR / 'SimpleTabulation-ICD-11-MMS-pt.xlsx'
CID11_VERSAO = '2025-01'
CID11_SHA256 = '80c187bcf70bd3a54d39e46865b769f47dcc34e2ee2a244d366e306dd6430472'
CID11_FONTE = 'https://icd.who.int/browse/2025-01/mms/pt'
CID11_LICENCA = (
    'CID-11 para Estatísticas de Mortalidade e de Morbidade (CID-11 MMS), versão 2025-01. '
    'Organização Mundial da Saúde. Licença CC BY-ND 3.0 IGO. Reproduzida sem alteração.'
)

#: Os capítulos que entram na busca; a razão de cada ausência está no topo.
CAPITULOS = frozenset(f'{n:02d}' for n in range(1, 26))

#: Abaixo disto a planilha não é a CID-11 inteira — é arquivo truncado ou
#: outro arquivo.
MINIMO_DE_CODIGOS = 15000

COLUNAS = ('Code', 'Title', 'TitleEN', 'ClassKind', 'ChapterNo')

#: Código-tronco: quatro posições, a segunda sempre letra, e até duas
#: depois do ponto.
_TRONCO = re.compile(r'^[0-9A-Z][A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,2})?$')
_TRACOS = re.compile(r'^(-\s+)+')


class PlanilhaInvalida(Exception):
    """A planilha não é a que se esperava; nada é gravado."""


def sistema_do_codigo(codigo):
    """`'CID10'`, `'CID11'` ou `''`, lido da forma do próprio código.

    Só as três primeiras posições decidem — letra e número é CID-10;
    qualquer coisa, letra e número é CID-11 —, de modo que o código
    incompleto que o médico digitou à mão e o agrupamento
    (`8A00.0&XK9J`) respondem igual ao código inteiro. A terceira posição
    entra na conta para que uma **palavra** não passe por código: a
    hipótese sem código chega aos documentos só com a descrição, e
    "Epilepsia focal" não é CID-11 por ter letra na segunda posição.
    """
    texto = (codigo or '').strip().upper()
    if len(texto) < 2 or not texto[:3].isascii() or not texto[0].isalnum():
        return ''
    if texto[0].isalpha() and texto[1].isdigit():
        return CID10
    if len(texto) >= 3 and texto[1].isalpha() and texto[2].isdigit():
        return CID11
    return ''


def rotulo_do_codigo(codigo, padrao=''):
    """`'CID-11'` ou `'CID-10'` para mostrar ao lado do código."""
    return ROTULOS.get(sistema_do_codigo(codigo), padrao)


def rotulo_da_hipotese(texto):
    """O rótulo de uma hipótese escrita como "código — descrição".

    É o que o documento imprime antes dela. Sem código reconhecível fica
    `CID-10`, que é o que o papel sempre disse.
    """
    partes = (texto or '').strip().split(None, 1)
    return rotulo_do_codigo(partes[0] if partes else '', padrao=ROTULOS[CID10])


def sistema_do_pedido(valor):
    """O parâmetro `sistema` de uma busca. Desconhecido é CID-10."""
    return CID11 if (valor or '').strip().upper().replace('-', '') == CID11 else CID10


def _pai(codigo):
    """`8A00.01` → `8A00.0` → `8A00`: a hierarquia está escrita no código."""
    if '.' not in codigo:
        return ''
    return codigo[:-1].rstrip('.')


def ler_planilha(caminho):
    """As linhas da tabulação simples da OMS, prontas para gravar.

    **Estrita**, como a leitura da Portaria 344: coluna faltando, código
    fora da forma, código repetido ou planilha curta levantam
    `PlanilhaInvalida`, e quem chama não grava nada. Uma CID-11 pela
    metade seria pior do que nenhuma — a busca responderia, e o código que
    faltasse pareceria não existir.
    """
    import openpyxl

    from .importers import normalize_for_search

    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        linhas = livro.active.iter_rows(values_only=True)
        cabecalho = [str(c or '').strip() for c in next(linhas, ())]
        faltando = [c for c in COLUNAS if c not in cabecalho]
        if faltando:
            raise PlanilhaInvalida(f'Colunas ausentes na planilha da CID-11: {", ".join(faltando)}')
        posicao = {c: cabecalho.index(c) for c in COLUNAS}

        def celula(linha, nome):
            valor = linha[posicao[nome]] if posicao[nome] < len(linha) else None
            return str(valor or '').strip()

        saida, vistos = [], set()
        for numero, linha in enumerate(linhas, start=2):
            codigo = celula(linha, 'Code')
            if not codigo or celula(linha, 'ClassKind') != 'category':
                continue
            if celula(linha, 'ChapterNo') not in CAPITULOS:
                continue
            # A tradução da OMS ainda não cobre tudo: 671 categorias
            # residuais ("outros especificados", "não especificado") vêm
            # com o título em português vazio. Entram com o título em
            # inglês **da própria planilha**, que é o que o navegador da
            # OMS mostra para elas — deixá-las de fora faria o código
            # parecer inexistente, e traduzir por conta própria seria
            # alterar a classificação, que a licença não permite.
            titulo = _TRACOS.sub('', celula(linha, 'Title')).strip()
            if not titulo:
                titulo = _TRACOS.sub('', celula(linha, 'TitleEN')).strip()
            if not _TRONCO.match(codigo) or not titulo:
                raise PlanilhaInvalida(f'Linha {numero}: código ou título fora do esperado ({codigo!r})')
            if codigo in vistos:
                raise PlanilhaInvalida(f'Linha {numero}: código repetido ({codigo})')
            vistos.add(codigo)
            saida.append({
                'code': codigo, 'description': titulo, 'parent_code': _pai(codigo),
                'search_text': normalize_for_search(f'{codigo} {titulo}'),
            })
    finally:
        livro.close()
    if len(saida) < MINIMO_DE_CODIGOS:
        raise PlanilhaInvalida(
            f'A planilha trouxe {len(saida)} códigos; a CID-11 tem mais de {MINIMO_DE_CODIGOS}.'
        )
    return saida


def sha256_do_arquivo(caminho):
    resumo = hashlib.sha256()
    with open(caminho, 'rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b''):
            resumo.update(bloco)
    return resumo.hexdigest()


def importar(caminho=CID11_ARQUIVO, versao=CID11_VERSAO, sha256_esperado=CID11_SHA256):
    """Grava e ativa a CID-11 da planilha, numa transação só.

    `sha256_esperado` vazio dispensa a conferência — é o que o comando
    `import_cid11` usa para uma versão nova, baixada depois desta.
    """
    from .importers import activate_release

    sha = sha256_do_arquivo(caminho)
    if sha256_esperado and sha != sha256_esperado:
        raise PlanilhaInvalida('A planilha da CID-11 não é a que foi conferida (SHA-256 diferente).')
    linhas = ler_planilha(caminho)
    with transaction.atomic():
        release = CatalogRelease.objects.create(
            system=CID11, version=versao, source_url=CID11_FONTE,
            imported_at=timezone.now(), content_sha256=sha,
            license_note=CID11_LICENCA, status=CatalogReleaseStatus.DRAFT,
        )
        DiagnosisCode.objects.bulk_create(
            [DiagnosisCode(release=release, **linha) for linha in linhas], batch_size=2000,
        )
        activate_release(release)
    return release, len(linhas)


def ensure_cid11(caminho=CID11_ARQUIVO, versao=CID11_VERSAO, sha256_esperado=CID11_SHA256):
    """Importa a CID-11 se a instalação ainda não tiver uma ativa.

    Mesmas duas regras de `provisioning.ensure_cid10`: **nunca sobrepõe**
    (a condição é haver release ativa, não haver esta versão) e **não
    levanta** — sem a CID-11 a clínica atende e registra hipótese pela
    CID-10, e derrubar a subida por causa de um catálogo deixaria todas
    fora do ar.
    """
    from django.db import IntegrityError

    from .provisioning import has_active_catalog

    if has_active_catalog(CID11):
        return None
    if not Path(caminho).is_file():
        logger.error('Planilha da CID-11 nao encontrada: %s', caminho)
        return None
    try:
        release, total = importar(caminho, versao, sha256_esperado)
    except IntegrityError:
        # Duas cópias do `app` sobem juntas e as duas leem a planilha; a
        # segunda a gravar esbarra no UNIQUE(system, version). Não é falha.
        logger.info('CID-11 %s ja importada por outro processo', versao)
        return None
    except Exception:
        logger.exception('Falha ao importar a CID-11 na subida da instalacao')
        return None
    logger.info('CID-11 %s importada e ativada (%s codigos)', versao, total)
    return release
