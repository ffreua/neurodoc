import re

from django.core.exceptions import ValidationError


def _only_digits(value):
    return re.sub(r'\D', '', value or '')


def _mod11_digit(digits, weights):
    total = sum(int(d) * w for d, w in zip(digits, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cpf(value):
    digits = _only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    d1 = _mod11_digit(digits[:9], range(10, 1, -1))
    d2 = _mod11_digit(digits[:9] + str(d1), range(11, 1, -1))
    return digits[-2:] == f'{d1}{d2}'


def normalizar_cnpj(value):
    """Tira máscara e espaço e põe em maiúsculas — **sem tirar letra**.

    O CNPJ alfanumérico (IN RFB 2.229/2024) é emitido desde 01/07/2026: os
    doze primeiros caracteres podem ser letras. Até a revisão de
    2026-11-02 este módulo descartava tudo que não era dígito antes de
    validar, e uma clínica aberta depois de julho não entrava com o
    próprio CNPJ — as letras sumiam e o que sobrava era recusado, ou
    pior, tomado por CPF.
    """
    return re.sub(r'[\s./-]', '', value or '').upper()


def _dv_cnpj(corpo, pesos):
    # Cálculo da Receita para o alfanumérico: cada caractere vale o código
    # ASCII menos 48 (dígito vale ele mesmo, `A` vale 17). Com só dígitos
    # é exatamente o módulo 11 de sempre, então todo CNPJ numérico válido
    # continua válido.
    resto = sum((ord(c) - 48) * p for c, p in zip(corpo, pesos)) % 11
    return '0' if resto < 2 else str(11 - resto)


def is_valid_cnpj(value):
    cnpj = normalizar_cnpj(value)
    if not re.fullmatch(r'[A-Z0-9]{12}[0-9]{2}', cnpj) or len(set(cnpj)) == 1:
        return False
    return (
        cnpj[12] == _dv_cnpj(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
        and cnpj[13] == _dv_cnpj(cnpj[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    )


def validate_cpf(value):
    if not is_valid_cpf(value):
        raise ValidationError('CPF inválido. Confira os onze dígitos.', code='invalid_cpf')


def validate_cnpj(value):
    if not is_valid_cnpj(value):
        raise ValidationError('CNPJ inválido. Confira os quatorze caracteres.', code='invalid_cnpj')
