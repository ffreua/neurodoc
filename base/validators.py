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


def is_valid_cnpj(value):
    digits = _only_digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    d1 = _mod11_digit(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _mod11_digit(digits[:12] + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == f'{d1}{d2}'


def validate_cpf(value):
    if not is_valid_cpf(value):
        raise ValidationError('Invalid CPF', code='invalid_cpf')


def validate_cnpj(value):
    if not is_valid_cnpj(value):
        raise ValidationError('Invalid CNPJ', code='invalid_cnpj')
