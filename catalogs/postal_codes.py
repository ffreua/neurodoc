"""Carga e consulta da base local de faixas de CEP.

A base vem do arquivo versionado `catalogs/data/postal_ranges.csv`, gerado a
partir da planilha pública de faixas dos Correios. Ela resolve município, UF
e código IBGE offline; logradouro e bairro **não** existem nesse conjunto de
dados (ver `PostalCodeRange`).
"""
import csv
import io
import re
from pathlib import Path

from django.db import transaction

from .models import PostalCodeRange, PostalRangeScope

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'postal_ranges.csv'

FIELDS = ('cep_start', 'cep_end', 'uf', 'city', 'city_ascii', 'region', 'ibge_code', 'by_street', 'scope')


def normalize_cep(value):
    """Devolve os 8 dígitos do CEP, ou None se não houver 8 dígitos."""
    digits = re.sub(r'\D', '', str(value or ''))
    return digits if len(digits) == 8 else None


def parse_rows(content_text):
    """Valida o CSV inteiro antes de qualquer escrita; devolve (linhas, erros)."""
    reader = csv.DictReader(io.StringIO(content_text))
    rows = []
    errors = []
    scopes = {choice for choice, _ in PostalRangeScope.choices}
    for line_number, row in enumerate(reader, start=2):
        start = normalize_cep(row.get('cep_start'))
        end = normalize_cep(row.get('cep_end'))
        uf = (row.get('uf') or '').strip().upper()
        city = (row.get('city') or '').strip()
        scope = (row.get('scope') or '').strip()
        if not start or not end:
            errors.append(f'Linha {line_number}: cep_start/cep_end precisam ter 8 dígitos')
            continue
        if end < start:
            errors.append(f'Linha {line_number}: cep_end ({end}) antes de cep_start ({start})')
            continue
        if len(uf) != 2 or not city:
            errors.append(f'Linha {line_number}: uf e city são obrigatórios')
            continue
        if scope not in scopes:
            errors.append(f'Linha {line_number}: scope desconhecido ({scope!r})')
            continue
        rows.append({
            'cep_start': start,
            'cep_end': end,
            'uf': uf,
            'city': city,
            'city_ascii': (row.get('city_ascii') or city).strip(),
            'region': (row.get('region') or '').strip(),
            'ibge_code': re.sub(r'\D', '', row.get('ibge_code') or ''),
            'by_street': (row.get('by_street') or '').strip() in ('1', 'true', 'True'),
            'scope': scope,
        })
    return rows, errors


def load_ranges(content_text, dry_run=True):
    """Substitui a tabela inteira pelo conteúdo do CSV.

    É uma tabela de referência sem nenhuma referência vinda de outro
    registro — nada aponta para uma faixa de CEP —, então recarregar é
    seguro e a substituição acontece numa transação só: ou a base nova
    inteira entra, ou a antiga permanece.
    """
    rows, errors = parse_rows(content_text)
    if dry_run or errors:
        return {'read': len(rows) + len(errors), 'written': 0, 'errors': errors}
    with transaction.atomic():
        PostalCodeRange.objects.all().delete()
        PostalCodeRange.objects.bulk_create(
            [PostalCodeRange(**row) for row in rows], batch_size=1000,
        )
    return {'read': len(rows), 'written': len(rows), 'errors': []}


def load_bundled_ranges(dry_run=True):
    return load_ranges(DATA_FILE.read_text(encoding='utf-8'), dry_run=dry_run)


def lookup_locality(cep):
    """Município/UF de um CEP, pela base local. None quando não há faixa.

    Entre faixas sobrepostas (todo município codificado por logradouro tem
    a faixa "total do município" e a "exclusiva da sede urbana", com os
    mesmos município e UF), escolhe deterministicamente a mais estreita.
    """
    digits = normalize_cep(cep)
    if not digits:
        return None
    match = (
        PostalCodeRange.objects
        .filter(cep_start__lte=digits, cep_end__gte=digits)
        # Entre duas faixas que contêm o mesmo ponto, a de início maior e
        # fim menor é a mais estreita.
        .order_by('-cep_start', 'cep_end', 'scope')
        .first()
    )
    if match is None:
        return None
    return {
        'city': match.city,
        'state': match.uf,
        'ibge_code': match.ibge_code,
        'region': match.region,
        'by_street': match.by_street,
        'source': 'correios-local',
    }
