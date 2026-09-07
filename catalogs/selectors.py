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
from .models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, DiagnosisCode

MAX_RESULTS = 20
MIN_TERM_CHARS = 2


def active_release(system=CatalogSystem.CID10):
    return CatalogRelease.objects.filter(
        system=system, status=CatalogReleaseStatus.ACTIVE,
    ).order_by('-imported_at').first()


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
        Q(search_text__contains=needle) | code_match
    )[: limit * 6]

    def rank(row):
        code = row.code.upper()
        code_bare = code.replace('.', '')
        if code_bare.startswith(bare):
            return (0, len(code), code)
        if normalize_for_search(row.description).startswith(needle):
            return (1, len(row.description), code)
        return (2, len(row.description), code)

    ordered = sorted(rows, key=rank)[:limit]
    return [
        {'id': str(row.id), 'code': row.code, 'description': row.description,
         'parent_code': row.parent_code}
        for row in ordered
    ]
