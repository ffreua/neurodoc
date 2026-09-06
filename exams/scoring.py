"""Pontuação de escalas funcionais.

Duas regras que a soma simples não cobre e que existem nas escalas reais:

- **itens em média.** A SARA avalia índex-nariz, diadococinesia e
  calcanhar-tornozelo nos dois lados e leva a **média** dos dois ao total,
  não a soma. Itens que compartilham `score_group` são tratados assim.
- **escala incompleta não vira escore.** Faltando item, o total é parcial e
  é isso que a tela diz; inventar o valor do item faltante seria fabricar
  medida clínica.
"""


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def band_for(scale, total):
    """Faixa de interpretação em que o total caiu, ou None."""
    if total is None:
        return None
    for band in scale.bands or []:
        low = band.get('min')
        high = band.get('max')
        if low is not None and total < low:
            continue
        if high is not None and total > high:
            continue
        return band.get('label') or None
    return None


def score(scale, items, values):
    """Calcula o total de uma escala.

    `values` mapeia código do item -> valor bruto (string ou número).
    Devolve um dicionário com o total, quantos itens foram preenchidos, se a
    escala está completa e a faixa de interpretação quando houver.
    """
    groups = {}
    answered = 0
    for item in items:
        raw = values.get(item.code)
        number = _numeric(raw)
        if number is None:
            continue
        answered += 1
        key = item.score_group or f'__{item.code}'
        groups.setdefault(key, []).append(number)

    total = None
    if answered:
        total = sum(sum(bucket) / len(bucket) for bucket in groups.values())
        # Escalas com pontuação inteira não devem exibir 12.0; as que têm
        # item em média (SARA) legitimamente têm meio ponto.
        total = round(total, 2)
        if total == int(total):
            total = int(total)

    expected = len(items)
    complete = answered == expected and expected > 0
    return {
        'total': total,
        'answered': answered,
        'expected': expected,
        'complete': complete,
        'band': band_for(scale, total) if complete else None,
    }


def render_summary(scale, result, values):
    """Resultado em texto curto, para o `qualifier` do achado e para o grid.

    Sem o nome da escala: no grid ele já é o rótulo da linha, e repeti-lo
    deixava "Epworth | Epworth: 16/24".
    """
    if result['total'] is None:
        return ''
    head = str(result['total'])
    if scale.max_score is not None:
        head += f'/{scale.max_score}'
    parts = [head]
    if not result['complete']:
        parts.append(f'parcial ({result["answered"]}/{result["expected"]} itens)')
    elif result['band']:
        parts.append(result['band'])
    return ' — '.join(parts)[:255]
