import csv
import io

SMALL_CELL_THRESHOLD = 5
# OWASP CSV-injection mitigation: any cell that a spreadsheet would treat
# as the start of a formula gets a leading apostrophe, which every major
# spreadsheet renders as literal text instead of evaluating.
_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_cell(value):
    text = '' if value is None else str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def export_csv(rows, fieldnames):
    """`rows` is a list of dicts; every value is sanitized against formula
    injection regardless of its source (all of them are server-computed
    here, but this stays defensive rather than assuming that forever).
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: sanitize_cell(row.get(key)) for key in fieldnames})
    return buf.getvalue()


def suppress_small_cells(rows, count_key, threshold=SMALL_CELL_THRESHOLD, other_label='Outros (células pequenas agregadas)'):
    """Managerial views never show a raw count below `threshold` -- it gets
    folded into an aggregate "other" row instead, to reduce the risk of
    reidentification by subtracting totals across cells.
    """
    visible = []
    suppressed_total = 0
    for row in rows:
        if row[count_key] < threshold:
            suppressed_total += row[count_key]
        else:
            visible.append(row)
    if suppressed_total:
        visible.append({count_key: suppressed_total, '_label': other_label})
    return visible


def export_json(rows):
    r"""As linhas como JSON, para levar a outro sistema.

    `ensure_ascii=False` porque o destino e um arquivo UTF-8 e nome de
    paciente tem acento: escapar tudo em `\uXXXX` dobra o tamanho e
    torna o arquivo ilegivel para quem abre para conferir.

    `default=str` cobre data, hora, `Decimal` e UUID -- que e o que
    aparece num despejo de banco e o que o serializador padrao recusa. A
    alternativa era converter campo por campo no `rows_fn` de cada
    relatorio, e a conversao esquecida derruba a exportacao no worker,
    longe de quem pediu.

    Sem `sanitize_cell`: aquilo defende planilha de formula, e JSON nao e
    planilha. Prefixar `=` aqui corromperia o dado no destino -- o
    conserto de um problema criaria outro.
    """
    import json

    return json.dumps(rows, ensure_ascii=False, indent=2, default=str)


def _celula_markdown(valor):
    """Uma celula de tabela Markdown, sem quebrar a tabela.

    Barra vertical fecha coluna e quebra de linha fecha a linha inteira:
    um endereco com `|` no meio desalinharia a tabela do ponto dele em
    diante, e ninguem repara numa tabela de mil linhas.
    """
    texto = '' if valor is None else str(valor)
    return texto.replace('|', r'\|').replace('\r\n', ' ').replace('\n', ' ').strip()


def export_markdown_table(rows, fieldnames, titulo=''):
    """As linhas como tabela Markdown. O formato de tabela, para dado de
    tabela -- texto longo pede documento, e quem o exporta passa o proprio
    renderizador ao registro (`markdown_fn`).
    """
    linhas = []
    if titulo:
        linhas += [f'# {titulo}', '']
    linhas.append('| ' + ' | '.join(fieldnames) + ' |')
    linhas.append('| ' + ' | '.join('---' for _ in fieldnames) + ' |')
    for row in rows:
        linhas.append(
            '| ' + ' | '.join(_celula_markdown(row.get(k)) for k in fieldnames) + ' |'
        )
    linhas.append('')
    return '\n'.join(linhas)
