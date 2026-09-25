"""Importação da lista de preços de medicamentos da CMED/Anvisa.

A planilha é publicada em XLSX, com 74 colunas e cerca de 26 mil linhas —
uma por **apresentação**, não por medicamento. Deste arquivo interessam
nove colunas: substância, produto, apresentação, laboratório, classe
terapêutica, tipo, tarja, registro e EAN. As 52 colunas de preço ficam de
fora (ver o comentário de `MedicationProduct`).

**As colunas são localizadas pelo nome do cabeçalho, nunca pela posição.**
A CMED republica o arquivo todo mês e já mudou a ordem das colunas de
preço entre publicações; um importador por índice leria laboratório na
coluna da substância e gravaria 26 mil linhas erradas sem falhar em nada.

**O cabeçalho não está na primeira linha.** As 41 primeiras são texto
explicativo da Secretaria Executiva, e a linha de cabeçalho é encontrada
por ser a primeira com mais de vinte células preenchidas — de novo, porque
o número de linhas de aviso muda entre publicações.

Quem baixa o arquivo é o **worker**: nesta topologia só ele alcança a
internet. Rodar o download dentro da requisição funcionaria no ambiente
local e travaria no timeout em produção, como todo o resto que fala com
serviço externo (ver `communications/mail_backend.py`).
"""

import hashlib
import unicodedata
from datetime import date

from django.db import transaction
from django.utils import timezone

from .importers import normalize_for_search
from .models import (
    CatalogRelease, CatalogReleaseStatus, CatalogSystem, MedicationProduct, MedicationTarja,
)

#: Endereço da lista mais recente. A CMED troca o nome do arquivo a cada
#: publicação (ele carrega a data e um carimbo de hora), então este valor é
#: ponto de partida e pode ser substituído por `--url` no comando.
URL_PADRAO = (
    'https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/'
    'xls_conformidade_site_20260909_222937320.xlsx/@@download/file'
)

#: Nome da coluna na planilha -> campo do modelo. A comparação é feita sobre
#: o cabeçalho normalizado (sem acento, maiúsculas, espaços colapsados),
#: porque a planilha alterna entre "SUBSTÂNCIA" e "SUBSTANCIA" e usa espaço
#: duplo em várias colunas.
COLUNAS = {
    'SUBSTANCIA': 'substance',
    'PRODUTO': 'product',
    'APRESENTACAO': 'presentation',
    'LABORATORIO': 'laboratory',
    'CLASSE TERAPEUTICA': 'therapeutic_class',
    'TIPO DE PRODUTO (STATUS DO PRODUTO)': 'product_type',
    'TARJA': 'tarja',
    'REGISTRO': 'registration',
    'EAN 1': 'ean',
    'CODIGO GGREM': 'ggrem',
}

#: Sem estas o registro não identifica nada, e a linha é descartada.
OBRIGATORIAS = ('ggrem', 'substance', 'presentation')

#: Texto da planilha -> tarja do modelo. A chave é o texto normalizado.
_TARJAS = {
    'TARJA PRETA': MedicationTarja.PRETA,
    'TARJA VERMELHA SOB RESTRICAO': MedicationTarja.VERMELHA_RESTRITA,
    'TARJA VERMELHA': MedicationTarja.VERMELHA,
    'TARJA SEM TARJA': MedicationTarja.SEM_TARJA,
    'SEM TARJA': MedicationTarja.SEM_TARJA,
}


class ImportacaoCmedErro(Exception):
    """Falha que impede a importação, com texto para quem rodou o comando."""


def _normaliza(texto):
    decomposto = unicodedata.normalize('NFKD', str(texto or ''))
    sem_acento = ''.join(c for c in decomposto if not unicodedata.combining(c))
    return ' '.join(sem_acento.upper().split())


def traduz_tarja(valor):
    """A tarja do modelo a partir do texto da planilha.

    O que não bate com nenhuma forma conhecida vira `NAO_INFORMADA`, e não
    `SEM_TARJA`: o `- (*)` da planilha é ausência de classificação, e
    afirmar "sem tarja" a partir dele seria o sistema inventando que o
    medicamento é isento de prescrição.
    """
    return _TARJAS.get(_normaliza(valor), MedicationTarja.NAO_INFORMADA)


def _linha_do_cabecalho(ws, limite=120):
    """A primeira linha com mais de vinte células preenchidas.

    As linhas anteriores são o texto explicativo da CMED, e quantas são
    muda entre publicações — contar um número fixo quebraria na primeira
    vez que a Secretaria acrescentasse um parágrafo.
    """
    for numero, linha in enumerate(ws.iter_rows(min_row=1, max_row=limite, values_only=True), 1):
        if sum(1 for c in linha if c not in (None, '')) > 20:
            return numero, linha
    raise ImportacaoCmedErro(
        'Não encontrei a linha de cabeçalho nas primeiras '
        f'{limite} linhas. O arquivo mudou de formato?'
    )


def _mapa_de_colunas(cabecalho):
    """Índice de cada coluna que interessa, pelo nome. Recusa se faltar uma.

    Recusar é o ponto: uma coluna que sumiu vira campo vazio em 26 mil
    linhas, e um catálogo de medicamentos pela metade é pior do que
    catálogo nenhum — ele parece que funcionou.
    """
    posicoes = {}
    for indice, titulo in enumerate(cabecalho):
        nome = _normaliza(titulo)
        if nome in COLUNAS and COLUNAS[nome] not in posicoes:
            posicoes[COLUNAS[nome]] = indice
    faltando = sorted(set(COLUNAS.values()) - set(posicoes))
    if faltando:
        raise ImportacaoCmedErro(
            f'Colunas ausentes na planilha: {", ".join(faltando)}. '
            'Confira se o arquivo é mesmo a lista de conformidade da CMED.'
        )
    return posicoes


def ler_planilha(caminho):
    """Lê o XLSX e devolve as linhas já no formato do modelo.

    `read_only` e `values_only`: a planilha tem 12 MB e 26 mil linhas, e
    carregar o objeto de célula de cada uma delas com estilo e formatação
    custa mais de um giga de memória — o worker tem 512 MB.
    """
    import openpyxl

    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        numero, cabecalho = _linha_do_cabecalho(ws)
        posicoes = _mapa_de_colunas(cabecalho)
        registros, vistos, descartadas = [], set(), 0
        for linha in ws.iter_rows(min_row=numero + 1, values_only=True):
            valores = {
                campo: str(linha[indice]).strip() if indice < len(linha) and linha[indice] is not None else ''
                for campo, indice in posicoes.items()
            }
            if any(not valores[c] for c in OBRIGATORIAS):
                descartadas += 1
                continue
            # A planilha repete o mesmo GGREM em publicações com correção;
            # a primeira ocorrência vale, e a segunda violaria o índice
            # único da release no meio do `bulk_create`.
            if valores['ggrem'] in vistos:
                descartadas += 1
                continue
            vistos.add(valores['ggrem'])
            valores['tarja'] = traduz_tarja(valores['tarja'])
            valores['search_text'] = normalize_for_search(
                f"{valores['substance']} {valores['product']} {valores['presentation']}"
            )
            registros.append(valores)
        return registros, descartadas
    finally:
        wb.close()


def sha256_do_arquivo(caminho):
    digest = hashlib.sha256()
    with open(caminho, 'rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b''):
            digest.update(bloco)
    return digest.hexdigest()


@transaction.atomic
def importar(caminho, versao=None, url='', ativar=True):
    """Cria uma release com as linhas da planilha e, se pedido, ativa-a.

    **Nunca toca numa release já importada.** Uma publicação nova é sempre
    uma release nova, pelo mesmo motivo do CID-10: a receita emitida em
    março guarda o texto que o medicamento tinha em março, e reescrever a
    linha antiga mudaria retroativamente o que foi prescrito.

    Ativar é o último passo e troca a release em vigor numa transação só —
    não existe instante em que a clínica fique sem catálogo ou com dois.
    """
    versao = versao or timezone.localdate().strftime('%Y-%m-%d')
    if CatalogRelease.objects.filter(system=CatalogSystem.CMED, version=versao).exists():
        raise ImportacaoCmedErro(
            f'Já existe uma release CMED versão {versao}. '
            'Use --versao para dar outro nome, ou apague a anterior.'
        )
    registros, descartadas = ler_planilha(caminho)
    if not registros:
        raise ImportacaoCmedErro('A planilha não produziu nenhuma linha válida.')

    release = CatalogRelease.objects.create(
        system=CatalogSystem.CMED, version=versao, source_url=url[:2048],
        content_sha256=sha256_do_arquivo(caminho), imported_at=timezone.now(),
        status=CatalogReleaseStatus.DRAFT,
        license_note=(
            'Lista de Preços de Medicamentos da CMED/Anvisa, de uso público. '
            'Importados apenas os campos de identificação do medicamento; '
            'as colunas de preço não são armazenadas.'
        ),
    )
    MedicationProduct.objects.bulk_create(
        [MedicationProduct(release=release, **valores) for valores in registros],
        batch_size=2000,
    )
    if ativar:
        CatalogRelease.objects.filter(
            system=CatalogSystem.CMED, status=CatalogReleaseStatus.ACTIVE,
        ).exclude(pk=release.pk).update(status=CatalogReleaseStatus.SUPERSEDED)
        release.status = CatalogReleaseStatus.ACTIVE
        release.save(update_fields=['status'])
    return release, len(registros), descartadas
