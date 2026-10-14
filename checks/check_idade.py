"""A idade ao lado do nome, na ficha e no prontuario.

Pedido de 2026-10-13. O que este roteiro cobra:

1. a conta: aniversario no dia conta, na vespera nao; abaixo de um ano sai
   em meses; ano estimado sai com "~"; sem dado, vazio;
2. no atendimento, a idade e a **da data do atendimento** -- a crianca
   atendida em 2019 aparece com a idade de 2019;
3. as telas usam o filtro, e o cabecalho do atendimento nao mostra mais
   "versao N" (o contador interno de gravacoes, que nao diz nada ao
   medico).
"""
from datetime import date, datetime
from pathlib import Path

from django.conf import settings as dj_settings
from django.utils import timezone

from base.templatetags.nd import nd_idade
from patients.models import Patient

failures = []


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


print('=== 1. a conta ===')
p = Patient(full_name='X', birth_date=date(1980, 5, 10))
confere(nd_idade(p, date(2026, 5, 9)) == '45 anos', 'vespera do aniversario', nd_idade(p, date(2026, 5, 9)))
confere(nd_idade(p, date(2026, 5, 10)) == '46 anos', 'dia do aniversario', nd_idade(p, date(2026, 5, 10)))
confere(nd_idade(Patient(birth_date=date(2025, 5, 10)), date(2026, 5, 10)) == '1 ano', 'singular')
bebe = Patient(birth_date=date(2026, 7, 20))
confere(nd_idade(bebe, date(2026, 10, 13)) == '2 meses', 'abaixo de um ano, em meses',
        nd_idade(bebe, date(2026, 10, 13)))
confere(nd_idade(bebe, date(2026, 8, 25)) == '1 mês', 'um mes', nd_idade(bebe, date(2026, 8, 25)))
confere(nd_idade(Patient(estimated_birth_year=1950), date(2026, 1, 1)) == '~76 anos',
        'ano estimado com til')
confere(nd_idade(Patient(birth_date_unknown_reason='nao sabe')) == '', 'sem dado, vazio')
confere(nd_idade(None) == '', 'sem paciente, vazio')
confere(nd_idade(Patient(birth_date=date(2030, 1, 1)), date(2026, 1, 1)) == '',
        'nascimento depois da data de referencia nao vira idade negativa')

print('=== 2. no atendimento, a idade daquela data ===')
crianca = Patient(birth_date=date(2015, 3, 1))
quando = timezone.make_aware(datetime(2019, 6, 1, 10, 0))
confere(nd_idade(crianca, quando) == '4 anos', 'a consulta de 2019 mostra 4 anos', nd_idade(crianca, quando))

print('=== 3. as telas ===')
raiz = Path(dj_settings.BASE_DIR) / 'templates'
cabecalho = (raiz / 'clinical' / '_encounter_header.html').read_text(encoding='utf-8')
confere('nd_idade:encounter.occurred_at' in cabecalho, 'o atendimento usa a idade da data dele')
confere('encounter.row_version' not in cabecalho, 'o selo "versao N" saiu do cabecalho')
ficha = (raiz / 'patients' / 'detail.html').read_text(encoding='utf-8')
nome = ficha.index('{{ patient.full_name }}</h4>')
confere('patient|nd_idade' in ficha[nome:nome + 300], 'a ficha mostra a idade logo depois do nome')
linha = (raiz / 'clinical' / 'timeline.html').read_text(encoding='utf-8')
confere('patient|nd_idade' in linha, 'a linha do tempo do prontuario mostra a idade')

print('---')
if failures:
    for item in failures:
        print('FALHA:', item)
    raise SystemExit(1)
print('OK: a idade aparece ao lado do nome, e no prontuario e a da data do atendimento.')
