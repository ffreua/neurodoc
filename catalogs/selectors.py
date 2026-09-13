"""Busca no catálogo de diagnósticos, para o autocomplete da tela.

Sempre na release **ativa**: um código digitado hoje tem de vir da versão em
vigor, e as versões antigas continuam no banco só para que um registro
clínico antigo permaneça legível com o texto que tinha quando foi feito.

A comparação é sobre `search_text` — código e descrição sem acento, em
maiúsculas —, com o termo digitado passando pela **mesma** normalização. É o
que faz "esclerose multipla" encontrar "Esclerose Múltipla", que é como a
busca é usada de fato.
"""

import re

from django.db.models import Q

from .importers import normalize_for_search
from .models import ProcedureCode, CatalogRelease, CatalogReleaseStatus, CatalogSystem, DiagnosisCode

MAX_RESULTS = 20
MIN_TERM_CHARS = 2


def active_release(system=CatalogSystem.CID10):
    return CatalogRelease.objects.filter(
        system=system, status=CatalogReleaseStatus.ACTIVE,
    ).order_by('-imported_at').first()



#: Sinonimos de busca: o que o medico digita -> o que a tabela escreve.
#:
#: A tabela da ANS abrevia. "RM - Cranio (encefalo)" e o codigo 41101014, e
#: quem procura por "ressonancia cranio" nao acha nada -- conclui que o
#: sistema nao tem o exame, e digita o codigo de cabeca ou liga para a
#: operadora. Sao 104 linhas comecando com "RX -", 51 com "US -", 37 com
#: "RM -" e 29 com "TC -": a abreviacao nao e excecao, e a regra da tabela.
#:
#: Cada token vira "este OU aquele" na consulta, e nao uma substituicao: quem
#: digita "RM" continua achando "RM", e quem digita "ressonancia" passa a
#: achar as duas formas. Substituir quebraria o primeiro caso.
#:
#: A lista e curta de proposito. Sinonimo e divida: cada entrada precisa
#: estar certa, e uma errada faz a busca trazer o que nao foi pedido, que e
#: pior do que nao trazer nada. Entram as abreviacoes que a propria tabela
#: usa, conferidas contra o conteudo importado.
SEARCH_SYNONYMS = {
    'RESSONANCIA': ['RM'],
    'TOMOGRAFIA': ['TC'],
    'ULTRASSOM': ['US'],
    'ULTRASSONOGRAFIA': ['US'],
    'RAIO': ['RX'],
    'RAIOX': ['RX'],
    'RADIOGRAFIA': ['RX'],
    'ELETROENCEFALOGRAMA': ['EEG'],
    'ELETRONEUROMIOGRAFIA': ['ENMG'],
    'CEREBRO': ['ENCEFALO'],
    'CABECA': ['CRANIO'],
}


def _token_variants(token):
    """As formas pelas quais este token pode aparecer na tabela."""
    return [token] + SEARCH_SYNONYMS.get(token, [])


def _token_filter(term_normalizado):
    """Um `Q` que exige **todas** as palavras, em qualquer ordem.

    A comparacao era pela frase inteira, e por isso "epilepsia mioclonica"
    nao achava "Epilepsia Mioclonica Progressiva" -- achava, mas
    "ressonancia cranio" nao achava "Ressonancia magnetica de cranio",
    porque as duas palavras nao aparecem coladas. Quem procura codigo
    digita duas ou tres palavras soltas do nome, nao o nome exato: e assim
    que a busca e usada de fato.

    `AND` e nao `OR`: com `OR`, "cranio" sozinho traria tudo o que menciona
    cranio, e a segunda palavra deixaria de restringir -- digitar mais
    devolveria mais resultados, que e o contrario do que se espera.

    Dentro de cada token, porem, as variantes sao `OR`: "ressonancia" casa
    com "RESSONANCIA" ou com "RM", porque e assim que a tabela da ANS
    escreve (ver `SEARCH_SYNONYMS`).
    """
    filtro = Q()
    for token in term_normalizado.split():
        variantes = Q()
        for forma in _token_variants(token):
            variantes |= Q(search_text__contains=forma)
        filtro &= variantes
    return filtro


def search_diagnosis_codes(term, limit=MAX_RESULTS):
    """Códigos que casam com `term`, por código ou por descrição.

    A ordenação põe o casamento por **início do código** na frente: quem
    digita "G40" quer G40 e seus subitens antes de qualquer descrição que
    mencione G40 no texto. Depois vem o início da descrição e, por último, o
    resto.
    """
    term = (term or '').strip()
    if len(term) < MIN_TERM_CHARS:
        return []
    release = active_release()
    if release is None:
        return []

    needle = normalize_for_search(term)
    # "g43.0", "G430" e "g43" têm de achar o mesmo código. O ponto do CID é
    # pontuação de apresentação: quem digita rápido no teclado numérico não o
    # digita, e o código no banco o tem.
    bare = needle.replace('.', '')
    candidates = {needle, bare}
    if re.fullmatch(r'[A-Z]\d{3,}', bare):
        candidates.add(f'{bare[:3]}.{bare[3:]}')

    code_match = Q()
    for candidate in candidates:
        code_match |= Q(code__startswith=candidate)

    rows = DiagnosisCode.objects.filter(release=release, active=True).filter(
        _token_filter(needle) | code_match
    )[: limit * 6]

    def rank(row):
        code = row.code.upper()
        code_bare = code.replace('.', '')
        descricao = normalize_for_search(row.description)
        if code_bare.startswith(bare):
            return (0, len(code), code)
        if descricao.startswith(needle):
            return (1, len(row.description), code)
        # A frase inteira, ainda que no meio, vem antes das palavras
        # espalhadas: quem digitou o nome exato quer o exato primeiro.
        if needle in descricao:
            return (2, len(row.description), code)
        return (3, len(row.description), code)

    ordered = sorted(rows, key=rank)[:limit]
    return [
        {'id': str(row.id), 'code': row.code, 'description': row.description,
         'parent_code': row.parent_code}
        for row in ordered
    ]


def search_procedure_codes(term, limit=MAX_RESULTS):
    """Procedimentos TUSS que casam com `term`, por codigo ou descricao.

    Le do espelho local alimentado pelo worker (`integrations.tuss.sync`).
    Mesma forma da busca de CID-10, e de proposito: quem mantem uma vai
    olhar a outra, e duas formas diferentes de fazer a mesma coisa e como
    uma delas fica para tras.

    A diferenca esta na ordenacao do codigo: o TUSS e numerico e sem ponto,
    entao nao ha as variantes que o CID exige ("g43.0", "G430", "g43").
    """
    term = (term or '').strip()
    if len(term) < MIN_TERM_CHARS:
        return []
    release = active_release(CatalogSystem.TUSS)
    if release is None:
        return []

    needle = normalize_for_search(term)
    rows = ProcedureCode.objects.filter(release=release).filter(
        _token_filter(needle) | Q(code__startswith=needle)
    )[: limit * 6]

    def rank(row):
        descricao = normalize_for_search(row.description)
        if row.code.startswith(needle):
            return (0, len(row.code), row.code)
        if descricao.startswith(needle):
            return (1, len(row.description), row.code)
        if needle in descricao:
            return (2, len(row.description), row.code)
        # Vigente antes de encerrado: procedimento fora de vigencia
        # continua na lista, com marca, mas nao na frente do que se pode
        # pedir hoje.
        return (3 if row.active else 4, len(row.description), row.code)

    ordered = sorted(rows, key=rank)[:limit]
    return [
        {'code': row.code, 'description': row.description,
         # `active` guarda a vigencia lida da ANS: procedimento encerrado
         # continua na lista, com marca. Some-lo esconderia por que a
         # operadora glosou um codigo que a clinica usou ate o mes passado.
         'in_force': row.active}
        for row in ordered
    ]
