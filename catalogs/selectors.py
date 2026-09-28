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
from .models import (
    CatalogRelease, CatalogReleaseStatus, CatalogSystem, DiagnosisCode, MedicationProduct,
    ProcedureCode,
)

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


# ------------------------------------------------------------ medicamentos

#: A busca de medicamento devolve mais linhas que a de código.
#:
#: A lista da CMED é por **apresentação**: "dipirona" tem dezenas de
#: entradas que diferem só na concentração e na embalagem, e cortar em vinte
#: esconderia justamente a apresentação que o médico procura. Trinta cabe
#: numa lista rolável sem virar catálogo.
MAX_MEDICAMENTOS = 30


def search_medications(term, limit=MAX_MEDICAMENTOS):
    """Apresentações que casam com `term`, por substância ou nome comercial.

    A ordenação põe na frente o que **começa** com o que foi digitado:
    quem digita "clonaz" quer clonazepam antes de um combinado que mencione
    clonazepam no meio da substância. Depois vem o nome comercial, e por
    último o resto.

    Cada resultado carrega a tarja e a sugestão de controle especial —
    "sugestão", e não decisão, pelo motivo escrito em `MedicationTarja`.
    """
    term = (term or '').strip()
    if len(term) < MIN_TERM_CHARS:
        return []
    release = active_release(CatalogSystem.CMED)
    if release is None:
        return []

    needle = normalize_for_search(term)
    linhas = MedicationProduct.objects.filter(release=release, active=True).filter(
        _token_filter(needle)
    )[: limit * 6]

    tokens = needle.split()
    primeiro = tokens[0] if tokens else needle

    def posicao(linha):
        substancia = normalize_for_search(linha.substance)
        produto = normalize_for_search(linha.product)
        texto = normalize_for_search(f'{linha.substance} {linha.product} {linha.presentation}')
        # Desempate por onde os termos aparecem, e não só alfabético.
        #
        # "dipirona 500" trazia 1000 MG na frente: o "500" casava com o
        # "X 500" da quantidade da caixa, no fim da apresentação, e a ordem
        # alfabética não distinguia isso de um "500 MG" no começo. Somar a
        # posição de cada termo põe na frente a linha em que eles aparecem
        # cedo — que é a dosagem, não o tamanho da embalagem.
        cedo = sum(texto.find(t) if t in texto else 999 for t in tokens)
        if substancia.startswith(primeiro):
            return (0, cedo, substancia, linha.presentation)
        if produto.startswith(primeiro):
            return (1, cedo, produto, linha.presentation)
        return (2, cedo, substancia, linha.presentation)

    resultados = []
    rotulos_vistos = set()
    for linha in sorted(linhas, key=posicao):
        rotulo = linha.rotulo()
        chave = normalize_for_search(rotulo)
        # A CMED tem uma linha por embalagem. Quando a tela mostra apenas
        # nome e concentração, caixas de 30 e 60 virariam duas opções
        # idênticas; uma só representa a escolha que o médico está fazendo.
        if chave in rotulos_vistos:
            continue
        rotulos_vistos.add(chave)
        resultados.append({
            'id': str(linha.id),
            'rotulo': rotulo,
            'dosagem': linha.dosagem_resumida(),
            'substancia': linha.substance[:200],
            'produto': linha.product,
            'apresentacao': linha.presentation,
            'laboratorio': linha.laboratory,
            'tarja': linha.tarja,
            'tarja_label': linha.get_tarja_display(),
            'controle_especial': linha.sugere_controle_especial,
        })
        if len(resultados) >= limit:
            break
    return resultados
