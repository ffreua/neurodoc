import csv
import io

from reporting.exporters import sanitize_cell


COMPETENCE_COLUMNS = (
    ('Paciente', 'patient'),
    ('Competência', 'competence_date'),
    ('Esperado', 'expected_amount'),
    ('Cobrado', 'charged_amount'),
    ('Status', 'status'),
    ('Número do recibo ou nota fiscal', 'fiscal_document_number'),
    ('Repasse previsto', 'doctor_share_amount'),
    ('Forma de pagamento', 'payment_category'),
)

CASH_COLUMNS = (
    ('Paciente', 'patient'),
    ('Recebido em', 'paid_at'),
    ('Valor', 'amount'),
    ('Método', 'method'),
    ('Referência bancária', 'external_reference'),
    ('Número do recibo ou nota fiscal', 'fiscal_document_number'),
)


def competence_rows(receivables):
    for receivable in receivables:
        snapshot = receivable.fee_snapshot or {}
        yield {
            'patient': receivable.patient.full_name,
            'competence_date': receivable.competence_date.isoformat(),
            'expected_amount': str(receivable.expected_amount),
            'charged_amount': str(receivable.charged_amount),
            'status': receivable.get_status_display(),
            'fiscal_document_number': receivable.fiscal_document_number,
            'doctor_share_amount': str(snapshot.get('doctor_share_amount') or ''),
            'payment_category': str(snapshot.get('payment_category') or ''),
        }


def cash_rows(payments):
    for payment in payments:
        yield {
            'patient': payment.receivable.patient.full_name,
            'paid_at': payment.paid_at.isoformat(),
            'amount': str(payment.amount),
            'method': payment.method,
            'external_reference': payment.external_reference,
            'fiscal_document_number': payment.receivable.fiscal_document_number,
        }


def render_excel_csv(rows, columns):
    """CSV UTF-8 com BOM e separador do Excel em português brasileiro."""
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
    writer.writerow([label for label, _key in columns])
    for row in rows:
        writer.writerow([sanitize_cell(row.get(key)) for _label, key in columns])
    return output.getvalue()
