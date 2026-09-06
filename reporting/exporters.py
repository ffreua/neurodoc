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
