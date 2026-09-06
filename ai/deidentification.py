import re

_CPF_PATTERN = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_PHONE_PATTERN = re.compile(r'\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b')
_EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_MIN_NAME_PART_LEN = 3


def _name_parts(full_name):
    return [p for p in (full_name or '').split() if len(p) >= _MIN_NAME_PART_LEN]


def deidentify_text(text, patient):
    """Local, rule-based redaction -- never a call to an external
    anonymization service (RF-11.06: the original identified text must
    never leave this process). Best-effort: exact-match on the patient's
    and mother's registered name parts, plus pattern-based scrubbing of
    CPF/phone/e-mail that catches values not on file too (a different
    person's number mentioned in free text, for instance).
    """
    if not text:
        return text
    result = text
    if patient is not None:
        for part in _name_parts(patient.full_name):
            result = re.sub(re.escape(part), '[PACIENTE]', result, flags=re.IGNORECASE)
        for part in _name_parts(getattr(patient, 'mother_name', '')):
            result = re.sub(re.escape(part), '[NOME_MAE]', result, flags=re.IGNORECASE)
        if getattr(patient, 'cpf', None):
            result = result.replace(patient.cpf, '[CPF]')
    result = _CPF_PATTERN.sub('[CPF]', result)
    result = _PHONE_PATTERN.sub('[TELEFONE]', result)
    result = _EMAIL_PATTERN.sub('[EMAIL]', result)
    return result


def deidentify_payload(payload, patient):
    return {
        key: deidentify_text(value, patient) if isinstance(value, str) else value
        for key, value in payload.items()
    }
