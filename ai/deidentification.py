import re
import unicodedata

#: **A fronteira de palavra que vale também dentro de um JSON.** O resumo,
#: o apoio diagnóstico e o relatório desidentificam o contexto **já
#: serializado** (`ai/services.py`), e no JSON a quebra de linha vira os
#: dois caracteres `\n`. Com o `\b` puro, "Anamnese:\nMaria refere…" não
#: tinha fronteira entre o `n` do escape e o `M` — o nome ia ao provedor
#: intacto, e o CPF no começo de linha também (auditoria de 2026-11-11).
#: Toda anotação que começa linha pelo nome do paciente caía nisso.
#:
#: Por isso a fronteira à esquerda aceita, além de "não é letra nem
#: dígito", o escape de controle do JSON (`\n`, `\t`, `\r`, `\f`, `\b`).
#: Recusada: desidentificar campo a campo antes de serializar. Resolveria
#: os três pedidos e deixaria aberto quem já chega com JSON pronto — o
#: próprio `check_ia_o_que_vai` faz isso —, e a regra precisa valer aqui,
#: por onde todo texto que vai a um provedor passa. O erro que sobra é o
#: de uma barra invertida literal antes de um "n", que redige a mais — o
#: lado seguro.
_INICIO = r'(?:(?<=\\[bfnrt])|(?<!\w))'
_FIM = r'(?!\w)'

_CPF_PATTERN = re.compile(_INICIO + r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}' + _FIM)
_PHONE_PATTERN = re.compile(_INICIO + r'(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}' + _FIM)
_EMAIL_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
_MIN_NAME_PART_LEN = 3

#: A frase (ou o trecho entre vírgulas) que fala de consanguinidade.
#:
#: **A consanguinidade não vai à IA** (decisão do responsável, 2026-11-02).
#: Ela é dado de saúde — sensível pela LGPD (art. 5º, II) como todo o
#: prontuário, que já sai desidentificado —, e o que a fazia especial era o
#: risco de **reidentificação** por combinação rara (doença rara +
#: genealogia + consanguinidade numa família pequena). Até aqui o tratamento
#: era travar o pedido inteiro ao achar a palavra; com o histórico do iClin,
#: cuja anamnese diz "nega consanguinidade", a IA ficou fechada para 972 dos
#: 2.217 pacientes migrados — 946 das 1.003 ocorrências eram negação. Agora
#: o trecho sai do texto e a IA trabalha sem esse dado; o médico continua
#: vendo tudo no prontuário.
#:
#: O trecho não atravessa aspas nem barra invertida: o texto pode ser um JSON
#: (`ai/services.py` desidentifica o contexto serializado), e o corte tem de
#: ficar dentro de um valor. À esquerda ele também para em dois-pontos, para
#: "AF: pais consanguíneos" manter o "AF:". `consang[uü]` pega a grafia com
#: trema, comum em texto antigo.
_CONSANGUINIDADE = re.compile(r'[^.;,:\n"\\]*consang[uü][^.;,\n"\\]*', re.IGNORECASE)
MARCADOR_CONSANGUINIDADE = '[consanguinidade omitida]'


def omitir_consanguinidade(text):
    """Tira do texto todo trecho que menciona consanguinidade."""
    if not text:
        return text

    def trocar(m):
        trecho = m.group(0)
        recuo = trecho[:len(trecho) - len(trecho.lstrip())]
        return f'{recuo}{MARCADOR_CONSANGUINIDADE}'

    return _CONSANGUINIDADE.sub(trocar, text)

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
    return re.sub(_INICIO + _padrao_sem_acento(part) + _FIM, marker, text, flags=re.IGNORECASE)


#: **O nome casa com e sem acento.** O cadastro grava "JOÃO PEREIRA"
#: (`patients.naming`), e o texto livre — sobretudo o migrado do iClin —
#: escreve "Joao". Comparando letra a letra, o primeiro nome passava.
_VARIANTES = {
    'a': 'aáàâãä', 'e': 'eéèêë', 'i': 'iíìîï', 'o': 'oóòôõö',
    'u': 'uúùûü', 'c': 'cç', 'n': 'nñ',
}


def _sem_acento(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if not unicodedata.combining(c)
    )


def _padrao_sem_acento(part):
    pedacos = []
    for letra in _sem_acento(part).lower():
        variantes = _VARIANTES.get(letra)
        pedacos.append(f'[{variantes}]' if variantes else re.escape(letra))
    return ''.join(pedacos)


def _redact_birth_date(text, nascimento):
    """Troca a data de nascimento do paciente, nas grafias de um laudo.

    Nenhum pedido manda a data de propósito — o relatório leva a idade —,
    mas ela chega pelo texto: cabeçalho de laudo colado, anamnese
    migrada. É a data **deste** paciente, e não qualquer data: a data do
    exame e a do início do sintoma são o que a IA precisa ler.
    """
    dia, mes, ano = nascimento.day, nascimento.month, nascimento.year
    grafias = [
        rf'0?{dia}[/.-]0?{mes}[/.-](?:{ano}|{ano % 100:02d})',
        rf'{ano}-{mes:02d}-{dia:02d}',
    ]
    padrao = r'(?<!\d)(?:' + '|'.join(grafias) + r')(?!\d)'
    return re.sub(padrao, '[NASCIMENTO]', text)


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
        if getattr(patient, 'birth_date', None):
            result = _redact_birth_date(result, patient.birth_date)
    result = _CPF_PATTERN.sub('[CPF]', result)
    result = _PHONE_PATTERN.sub('[TELEFONE]', result)
    result = _EMAIL_PATTERN.sub('[EMAIL]', result)
    # Aqui, e não em cada chamador: todo texto que vai a um provedor de IA
    # passa por esta função — os três tipos de pedido e o chat (contexto,
    # histórico e pergunta).
    result = omitir_consanguinidade(result)
    return result


def deidentify_payload(payload, patient):
    return {
        key: deidentify_text(value, patient) if isinstance(value, str) else value
        for key, value in payload.items()
    }
