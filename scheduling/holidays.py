"""Feriados nacionais brasileiros, calculados.

Não são baixados de serviço nenhum, e isso é deliberado: os fixos são fixos
por lei, e os móveis derivam da Páscoa por aritmética. Calcular funciona para
qualquer ano, sem rede, e não depende de uma API continuar no ar — numa
agenda publicada para o ano inteiro, essa diferença importa.

Estadual e municipal **não** entram aqui. Não são calculáveis: variam por lei
local e mudam. Esses são cadastrados pela organização (`Holiday` com
`source='manual'`), e a maioria tem data fixa, então cadastrar uma vez cobre
todos os anos.

O que este módulo **não** faz: bloquear a agenda. Ele só diz que a data é
feriado. Bloquear é decisão do médico, tomada na tela de revisão — atender em
feriado acontece (plantão, mutirão, reposição).
"""

from datetime import date, timedelta

#: Feriados nacionais de data fixa (Lei 662/1949, Lei 6.802/1980 e a
#: Consciência Negra, nacional desde a Lei 14.759/2023).
FIXED_NATIONAL = (
    ((1, 1), 'Confraternização Universal'),
    ((4, 21), 'Tiradentes'),
    ((5, 1), 'Dia do Trabalho'),
    ((9, 7), 'Independência do Brasil'),
    ((10, 12), 'Nossa Senhora Aparecida'),
    ((11, 2), 'Finados'),
    ((11, 15), 'Proclamação da República'),
    ((11, 20), 'Consciência Negra'),
    ((12, 25), 'Natal'),
)

#: Pontos facultativos de fato tratados como feriado na maior parte do país.
#: Ficam separados porque **não são feriado nacional**: Carnaval e a
#: quarta-feira de cinzas são ponto facultativo, e quinta-feira santa não é
#: nem isso. Entram na lista de sugestão marcados como facultativos, para o
#: médico decidir — o que é diferente de o sistema afirmar que é feriado.
EASTER_OFFSETS = (
    (-48, 'Carnaval (segunda-feira)', True),
    (-47, 'Carnaval (terça-feira)', True),
    (-46, 'Quarta-feira de Cinzas (até 14h)', True),
    (-2, 'Sexta-feira Santa', False),
    (60, 'Corpus Christi', True),
)


def easter_sunday(year):
    """Domingo de Páscoa, pelo algoritmo gregoriano anônimo.

    É aritmética pura e vale para todo o calendário gregoriano; nenhuma
    tabela para manter, nenhum ano para atualizar.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    lunar = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lunar) // 451
    month = (h + lunar - 7 * m + 114) // 31
    day = ((h + lunar - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def national_holidays(year):
    """Feriados e pontos facultativos nacionais do ano.

    Devolve lista de dicionários com `date`, `name`, `recurring` (falso para
    os móveis, que mudam de data todo ano) e `optional` (ponto facultativo,
    não feriado).
    """
    rows = [
        {'date': date(year, month, day), 'name': name, 'recurring': True, 'optional': False}
        for (month, day), name in FIXED_NATIONAL
    ]
    easter = easter_sunday(year)
    for offset, name, optional in EASTER_OFFSETS:
        rows.append({
            'date': easter + timedelta(days=offset), 'name': name,
            'recurring': False, 'optional': optional,
        })
    return sorted(rows, key=lambda row: row['date'])


def expand_recurring(holiday, year):
    """A data que um feriado recorrente ocupa no ano pedido, ou None.

    Fevereiro de 29 num ano comum simplesmente não existe: em vez de
    deslocar para 28 (inventando uma data), o feriado não aparece naquele
    ano.
    """
    if not holiday.recurring:
        return holiday.date if holiday.date.year == year else None
    try:
        return date(year, holiday.date.month, holiday.date.day)
    except ValueError:
        return None


def holidays_in_range(tenant_id, start, end, state='', city=''):
    """Feriados que caem no intervalo, para o lugar onde o médico atende.

    Junta o que está cadastrado (`Holiday`) com a expansão dos recorrentes
    ano a ano. A chave de deduplicação é `(data, nome)`: o mesmo feriado
    cadastrado como recorrente e como data específica não deve aparecer duas
    vezes na tela de revisão.
    """
    from .models import Holiday

    stored = Holiday.objects.filter(tenant_id=tenant_id, active=True)
    found = {}
    for year in range(start.year, end.year + 1):
        for holiday in stored:
            if not holiday.applies_to(state=state, city=city):
                continue
            occurrence = expand_recurring(holiday, year)
            if occurrence is None or not (start <= occurrence <= end):
                continue
            found[(occurrence, holiday.name)] = {
                'date': occurrence, 'name': holiday.name, 'scope': holiday.scope,
                # O rótulo em português vem junto: a tela mostrava o valor
                # cru do enum ("national", "municipal").
                'scope_label': holiday.get_scope_display(),
                'holiday_id': holiday.id,
            }
    return sorted(found.values(), key=lambda row: row['date'])
