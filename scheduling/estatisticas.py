"""Estatísticas do mês: o que a agenda já sabe, somado.

A pergunta que a clínica faz no fim do mês — "quantas primeiras consultas
eu vi?", "sobrou horário?" — já tinha resposta no banco e não tinha tela.
Quem precisava contava à mão, na agenda, dia por dia.

**Mês a mês, e nunca acumulado.** Uma média de doze meses esconde o que
interessa: o mês em que as primeiras consultas caíram pela metade. A
comparação com o mês anterior vem ao lado, e é a única comparação que esta
tela faz.

**Capacidade de agenda, não clínica.** A tela mostra **contagens**, nunca
nome de paciente nem diagnóstico. É informação de operação do consultório,
e quem opera o consultório é a recepção tanto quanto o médico — o PRD dá a
linha da agenda aos quatro papéis, e esta tela fica do mesmo lado dela.

**Três conjuntos que não se misturam, e a distinção é o valor da tela:**

- **atendidos** — o paciente veio. `Concluído`, `Em atendimento` e
  `Check-in feito`;
- **agendados** — ainda na agenda, esperando acontecer. Num mês passado
  isto é resíduo (ninguém fechou o atendimento), e ver o número é o
  caminho para corrigir;
- **faltas** e **cancelados** — contados à parte. Somá-los a "atendidos"
  infla o movimento do mês com gente que não apareceu, e é o erro que
  torna um relatório de produtividade inútil.

A ocupação dos horários vem da **mesma grade que desenha a agenda**
(`month_summary`), e não de uma segunda conta: duas contas do mesmo número
divergem no primeiro ajuste de regra de horário, e aí a tela e a agenda
passam a discordar sobre quantas vagas existem.
"""
from calendar import monthrange
from datetime import date, timedelta

from .availability import month_summary
from .models import Appointment, AppointmentStatus, AppointmentType

#: Status que significam "o paciente veio".
ATENDIDOS = (
    AppointmentStatus.COMPLETED,
    AppointmentStatus.IN_PROGRESS,
    AppointmentStatus.CHECKED_IN,
)
#: Status que significam "está marcado e ainda vai acontecer".
AGENDADOS = (AppointmentStatus.SCHEDULED, AppointmentStatus.CONFIRMED)

#: A ordem em que os tipos aparecem na tela. Primeira consulta primeiro
#: porque é o número que diz se a clínica está crescendo; os demais
#: descrevem o acompanhamento de quem já é paciente.
ORDEM_DOS_TIPOS = (
    AppointmentType.FIRST_VISIT,
    AppointmentType.FOLLOW_UP,
    AppointmentType.RETURN_VISIT,
    AppointmentType.PROCEDURE,
    AppointmentType.OTHER,
)


def limites_do_mes(ano, mes):
    """O primeiro e o último dia do mês, e o mês anterior."""
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, monthrange(ano, mes)[1])
    anterior = primeiro - timedelta(days=1)
    return primeiro, ultimo, (anterior.year, anterior.month)


def _por_tipo(tenant_id, primeiro, ultimo, physician_membership_id=None):
    """Contagem por tipo de atendimento, separando o que aconteceu do resto.

    Uma consulta por linha de resultado, em vez de cinco consultas por
    tipo: a contagem é feita em Python sobre quatro colunas, que é barato,
    e o banco responde uma vez.
    """
    consulta = Appointment.objects.filter(
        tenant_id=tenant_id, starts_at__date__gte=primeiro, starts_at__date__lte=ultimo,
    )
    if physician_membership_id:
        consulta = consulta.filter(physician_membership_id=physician_membership_id)

    vazio = {'atendidos': 0, 'agendados': 0, 'faltas': 0, 'cancelados': 0}
    por_tipo = {tipo: dict(vazio) for tipo in ORDEM_DOS_TIPOS}
    totais = dict(vazio)

    for tipo, status in consulta.values_list('type', 'status'):
        alvo = por_tipo.setdefault(tipo, dict(vazio))
        if status in ATENDIDOS:
            chave = 'atendidos'
        elif status in AGENDADOS:
            chave = 'agendados'
        elif status == AppointmentStatus.NO_SHOW:
            chave = 'faltas'
        else:
            chave = 'cancelados'
        alvo[chave] += 1
        totais[chave] += 1
    return por_tipo, totais


def _ocupacao(primeiro, ultimo, medicos):
    """Quantos horários existiram no mês, e o que aconteceu com cada um.

    Soma a grade de cada médico. Vem de `month_summary`, a mesma função que
    desenha a agenda — se esta tela fizesse a própria conta, as duas
    divergiriam no primeiro ajuste de regra de horário, e ninguém saberia
    qual acreditar.
    """
    dias = [
        primeiro + timedelta(days=n)
        for n in range((ultimo - primeiro).days + 1)
    ]
    soma = {'total': 0, 'ocupados': 0, 'atendidos': 0, 'vagos': 0,
            'livres': 0, 'bloqueados': 0}
    por_medico = []
    for medico in medicos:
        resumo = month_summary(medico.id, dias)
        linha = {'medico': medico, 'total': 0, 'ocupados': 0, 'atendidos': 0,
                 'vagos': 0, 'livres': 0, 'bloqueados': 0}
        for dados in resumo.values():
            celulas = dados['cells']
            linha['total'] += len(celulas)
            linha['livres'] += dados['free']
            linha['vagos'] += dados['past']
            linha['bloqueados'] += dados['blocked']
            linha['ocupados'] += sum(1 for c in celulas if c['status'] == 'busy')
            linha['atendidos'] += sum(1 for c in celulas if c['status'] == 'done')
        for chave in soma:
            soma[chave] += linha[chave]
        por_medico.append(linha)

    # "Usados" é o que o horário de fato absorveu: quem está lá agora e
    # quem já foi atendido. A taxa usa o total de horários **que existiram**
    # e não só os passados -- do contrário um mês mal começado mostraria
    # ocupação de 100% por ter uma consulta e nenhum horário vencido.
    usados = soma['ocupados'] + soma['atendidos']
    soma['usados'] = usados
    soma['taxa'] = round(100 * usados / soma['total'], 1) if soma['total'] else 0.0
    return soma, por_medico


def do_mes(tenant_id, ano, mes, medicos, physician_membership_id=None):
    """Tudo que a tela do mês mostra, numa estrutura só.

    `medicos` chega de fora (a view já os carrega para o seletor) para esta
    função não repetir a consulta de vínculos.
    """
    primeiro, ultimo, (ano_ant, mes_ant) = limites_do_mes(ano, mes)
    alvo = [m for m in medicos if not physician_membership_id
            or str(m.id) == str(physician_membership_id)]

    por_tipo, totais = _por_tipo(tenant_id, primeiro, ultimo, physician_membership_id)
    ocupacao, por_medico = _ocupacao(primeiro, ultimo, alvo)

    # O mês anterior, só nos números de atendimento: repetir a varredura de
    # grade dobraria o custo da tela para uma comparação que ninguém pediu
    # em horários.
    p_ant, u_ant, _ = limites_do_mes(ano_ant, mes_ant)
    _, totais_ant = _por_tipo(tenant_id, p_ant, u_ant, physician_membership_id)

    linhas = [
        {
            'tipo': tipo,
            'rotulo': AppointmentType(tipo).label,
            **por_tipo.get(tipo, {}),
        }
        for tipo in ORDEM_DOS_TIPOS
    ]
    return {
        'primeiro': primeiro,
        'ultimo': ultimo,
        'linhas': linhas,
        'totais': totais,
        'totais_anteriores': totais_ant,
        'variacao': totais['atendidos'] - totais_ant['atendidos'],
        'ocupacao': ocupacao,
        'por_medico': por_medico,
        'mes_anterior': (ano_ant, mes_ant),
    }
