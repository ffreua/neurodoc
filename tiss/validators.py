"""Identificadores do faturamento TISS: CNPJ alfanumérico, registro ANS, CNES.

**Por que não `base.validators.is_valid_cnpj`.** Aquele descarta tudo que
não é dígito antes de validar, e é o certo para o CNPJ da clínica no
contrato. Mas o XSD 4.03.00 já declara `st_CNPJ` como `[A-Z0-9]{12}[0-9]{2}`
(o CNPJ alfanumérico da IN RFB 2.229/2024, eficaz desde 01/07/2026, A3
§314): um CNPJ com letra passado por aquele validador seria mutilado ou
recusado. Este vale **só no TISS**; o `Tenant.cnpj` fica como está.

O cálculo é o da Receita para o alfanumérico: cada caractere vale o seu
código ASCII menos 48 (dígito vale ele mesmo; `A` vale 17), com os mesmos
pesos e o mesmo módulo 11 do numérico — por isso todo CNPJ numérico válido
continua válido aqui.
"""

import re

_PESOS_1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_PESOS_2 = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def normalizar_cnpj(valor):
    """Tira máscara e espaço, e põe em maiúsculas. Não tira letra."""
    return re.sub(r'[\s./-]', '', valor or '').upper()


def _dv(corpo, pesos):
    soma = sum((ord(c) - 48) * p for c, p in zip(corpo, pesos))
    resto = soma % 11
    return '0' if resto < 2 else str(11 - resto)


def cnpj_valido(valor):
    cnpj = normalizar_cnpj(valor)
    if not re.fullmatch(r'[A-Z0-9]{12}[0-9]{2}', cnpj):
        return False
    if len(set(cnpj)) == 1:
        return False
    return cnpj[12] == _dv(cnpj[:12], _PESOS_1) and cnpj[13] == _dv(cnpj[:13], _PESOS_2)


def cnpj_alfanumerico(valor):
    """Tem letra — e por isso só cabe nas versões que aceitam (4.03.00 em diante)."""
    return bool(re.search(r'[A-Z]', normalizar_cnpj(valor)))


def registro_ans_valido(valor):
    """`st_registroANS`: exatamente seis dígitos, zero à esquerda incluso."""
    return bool(re.fullmatch(r'[0-9]{6}', (valor or '').strip()))


def cnes_valido(valor):
    """CNES tem sete dígitos (`st_texto7`). A ANS manda usar 9999999 quando não há."""
    return bool(re.fullmatch(r'[0-9]{7}', (valor or '').strip()))
