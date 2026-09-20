import re

_CPF_PATTERN = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_PHONE_PATTERN = re.compile(r'\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}\b')
_EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_MIN_NAME_PART_LEN = 3

#: Partes de nome que nao identificam ninguem sozinhas, e que aparecem em
#: texto clinico com outro sentido. Sem esta lista, um paciente chamado
#: "Maria das Gracas" faz "todas as noites" virar "to[PACIENTE] as
#: noites" -- e com a fronteira de palavra ja em vigor continuaria fazendo
#: "dor das pernas" virar "dor [PACIENTE] pernas".
#:
#: Os sufixos de geracao entram pelo mesmo motivo: "Filho" e "Neto" sao
#: parte do nome, mas o que identifica sao as partes ja substituidas -- e
#: "o filho do paciente relata" e frase de anamnese, nao nome de gente.
_NAME_PARTICLES = frozenset({
    'das', 'dos', 'del', 'della', 'van', 'von', 'bin', 'ibn',
    'filho', 'filha', 'junior', 'neto', 'neta', 'sobrinho', 'sobrinha',
    'segundo', 'terceiro',
})


def _name_parts(full_name):
    return [
        p for p in (full_name or '').split()
        if len(p) >= _MIN_NAME_PART_LEN and p.lower() not in _NAME_PARTICLES
    ]


def _redact_name_part(text, part, marker):
    """Troca `part` por `marker`, mas so quando ela e uma palavra inteira.

    Sem a fronteira de palavra -- que e como esta funcao nasceu -- a
    substituicao comia pedaco de termo clinico: uma paciente chamada Ana
    fazia "Anamnese" virar "[PACIENTE]mnese", um Dan fazia "danos
    neurologicos" virar "[PACIENTE]os neurologicos". O texto adulterado ia
    ao provedor e voltava como analise de uma consulta que ninguem
    escreveu.

    O `\b` do Python ja e unicode para `str`, entao nome acentuado (Joao,
    Ines) casa normalmente.

    Fica de fora, de proposito, o sobrenome que tambem e palavra comum:
    um paciente "Joao Campos" continua fazendo "campos visuais" virar
    "[PACIENTE] visuais". E o lado seguro do erro -- redigir demais nao
    vaza nome de ninguem -- e nao da para distinguir os dois sem saber
    qual dos dois sentidos a frase quis dizer.
    """
    return re.sub(rf'\b{re.escape(part)}\b', marker, text, flags=re.IGNORECASE)


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
            result = _redact_name_part(result, part, '[PACIENTE]')
        for part in _name_parts(getattr(patient, 'mother_name', '')):
            result = _redact_name_part(result, part, '[NOME_MAE]')
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
