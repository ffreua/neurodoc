"""Dashboard: o perfil da carteira e da atividade, por clínica e por médico.

Os indicadores antigos (`reporting/patients.py` e a tela "Indicadores")
respondem a perguntas de caixa — faturamento, repasse, falta. Este módulo
responde às de quem quer conhecer a carteira: quem são os pacientes (idade,
sexo, onde moram, como chegaram, como pagam), o que eles têm (CID) e como a
atividade anda mês a mês. Tudo agregado: nenhuma função daqui devolve linha
de paciente.

**O escopo é decidido aqui, e não na tela.** Duas fronteiras, as duas
conferidas no servidor:

- **Clínica.** Sempre e só a da sessão (`access_context.tenant_id`). Juntar
  duas clínicas numa conta seria atravessar o isolamento que o produto
  inteiro sustenta; quem atende em várias troca de organização, e a tela
  oferece a troca pelo caminho de sempre (`accounts:switch-tenant`).
- **Médico.** Quem administra a clínica — o responsável e o gestor — vê a
  clínica inteira e pode escolher um médico. O médico que não administra
  vê **só a própria carteira**, e o `?medico=` da URL é ignorado para ele:
  o painel de um colega não é dele para abrir. A recusa é silenciosa (cai
  no próprio escopo) porque o parâmetro chega pela URL, e URL guardada nos
  favoritos de quem perdeu o papel de gestor não deve virar erro.

**"Paciente do médico"** é quem tem com ele um atendimento (qualquer estado)
ou um horário que não foi cancelado. Só o atendimento deixaria de fora quem
marcou e ainda não veio; só o horário deixaria de fora o histórico migrado
do iClin, que não tem agenda.

**O CID exige `READ_CLINICAL`.** O responsável que não é médico administra
a clínica e não abre prontuário (`capabilities_for`); a distribuição de
diagnósticos da carteira é informação clínica, ainda que agregada. A mesma
linha que separa `por_cid.py` da lista de pacientes.

**Município com poucos pacientes vai para "Outros".** É a regra que já
estava em `patients.location_distribution` (menos de
`SMALL_CELL_THRESHOLD`): a tabela por município é a que sai em CSV e pode
ser mandada adiante, e uma cidade com um paciente só identifica a pessoa.
A tabela por UF não precisa disso.
"""
import datetime
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

from django.db.models import Count, Min, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from clinical.models import DiagnosisCertainty, Encounter, EncounterDiagnosis, EncounterStatus
from patients.models import (
    Patient, PatientCoverage, PatientStatus, PaymentCategory, ReferralSource,
    RegistrationStage, SexAtRegistration,
)
from scheduling.models import Appointment, AppointmentStatus
from tenancy.models import Membership, Role
from tenancy.permissions import Capability

from .exporters import SMALL_CELL_THRESHOLD

#: Faixas etárias, em anos completos. A primeira separa criança e
#: adolescente porque é a pergunta mais comum de quem atende neuropediatria;
#: as demais em décadas, que é como a epidemiologia apresenta.
FAIXAS_ETARIAS = (
    (0, 17, '0 a 17'), (18, 29, '18 a 29'), (30, 39, '30 a 39'), (40, 49, '40 a 49'),
    (50, 59, '50 a 59'), (60, 69, '60 a 69'), (70, 79, '70 a 79'), (80, 200, '80 ou mais'),
)

#: Teto de meses do gráfico mensal. O período pode ser longo (o histórico do
#: iClin vem de anos atrás); o gráfico mostra os últimos 24 meses dele, e a
#: tela diz isso, em vez de desenhar duzentas colunas de um pixel.
MAX_MESES = 24

#: Quantas linhas os rankings mostram. O CSV traz todas.
TOPO = 15

PERIODOS = OrderedDict([
    ('30d', 'Últimos 30 dias'),
    ('90d', 'Últimos 90 dias'),
    ('12m', 'Últimos 12 meses'),
    ('ano', 'Este ano'),
    ('tudo', 'Desde o início'),
])
PERIODO_PADRAO = '12m'


@dataclass(frozen=True)
class Escopo:
    tenant_id: object
    membership_id: object
    medico: object  # `Membership` ou `None` = a clínica inteira
    ve_clinica_inteira: bool
    clinico: bool
    pode_exportar_mailing: bool
    inicio: datetime.date
    fim: datetime.date
    periodo: str
    medicos: tuple = field(default_factory=tuple)

    @property
    def medico_id(self):
        return str(self.medico.id) if self.medico else ''


def _data(valor):
    try:
        return datetime.date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def periodo_da_requisicao(params, hoje=None):
    """O período escolhido, e o padrão quando não veio nenhum ou veio ilegível.

    Data ilegível cai no padrão em vez de derrubar a página — a mesma regra
    de `views._parse_period`, pelo mesmo motivo: a URL é digitada e colada
    pela metade. Datas trocadas são desinvertidas.
    """
    hoje = hoje or timezone.localdate()
    inicio, fim = _data(params.get('inicio')), _data(params.get('fim'))
    if inicio or fim:
        inicio = inicio or fim
        fim = fim or hoje
        if fim < inicio:
            inicio, fim = fim, inicio
        return inicio, fim, 'personalizado'
    codigo = params.get('periodo')
    if codigo not in PERIODOS:
        codigo = PERIODO_PADRAO
    if codigo == '30d':
        return hoje - datetime.timedelta(days=29), hoje, codigo
    if codigo == '90d':
        return hoje - datetime.timedelta(days=89), hoje, codigo
    if codigo == 'ano':
        return hoje.replace(month=1, day=1), hoje, codigo
    if codigo == 'tudo':
        return datetime.date(2000, 1, 1), hoje, codigo
    # 12 meses: do primeiro dia do mês de onze meses atrás, para o gráfico
    # mensal fechar doze colunas inteiras.
    ano, mes = hoje.year, hoje.month - 11
    while mes <= 0:
        mes += 12
        ano -= 1
    return datetime.date(ano, mes, 1), hoje, codigo


def medicos_da_clinica(tenant_id):
    """Vínculos com o papel médico nesta clínica, os inativos ao fim.

    Inclui quem saiu: a carteira atendida por um médico que deixou a
    clínica continua sendo pergunta legítima do responsável.
    """
    vinculos = (
        Membership.objects.filter(tenant_id=tenant_id, roles__contains=[Role.DOCTOR])
        .select_related('user')
    )
    return tuple(sorted(
        vinculos, key=lambda m: (m.status != 'active', m.user.get_full_name().lower()),
    ))


def resolver_escopo(access_context, params):
    """O escopo desta requisição. Quem decide o médico é o papel, não a URL."""
    ctx = access_context
    ve_clinica_inteira = ctx.can(Capability.MANAGE_ORGANIZATION) or ctx.has_role(Role.MANAGER)
    medicos = medicos_da_clinica(ctx.tenant_id)
    inicio, fim, periodo = periodo_da_requisicao(params)

    if ve_clinica_inteira:
        pedido = params.get('medico') or ''
        medico = next((m for m in medicos if str(m.id) == pedido), None)
        opcoes = medicos
    else:
        medico = next((m for m in medicos if m.id == ctx.membership_id), None)
        if medico is None:
            # Chegou ao painel sem ser médico nem administrar: só o próprio
            # vínculo, e ele não tem carteira. Escopo vazio, nunca a clínica.
            medico = Membership.objects.filter(id=ctx.membership_id).select_related('user').first()
        opcoes = (medico,) if medico else ()

    return Escopo(
        tenant_id=ctx.tenant_id, membership_id=ctx.membership_id, medico=medico,
        ve_clinica_inteira=ve_clinica_inteira, clinico=ctx.can(Capability.READ_CLINICAL),
        pode_exportar_mailing=ctx.can(Capability.MANAGE_ORGANIZATION),
        inicio=inicio, fim=fim, periodo=periodo, medicos=opcoes,
    )


# ------------------------------------------------------------ consultas base

def _ids_do_medico(tenant_id, medico):
    atendidos = Encounter.objects.filter(tenant_id=tenant_id, physician_membership=medico).values('patient_id')
    marcados = (
        Appointment.objects.filter(tenant_id=tenant_id, physician_membership=medico)
        .exclude(status=AppointmentStatus.CANCELLED).values('patient_id')
    )
    return atendidos, marcados


def carteira(escopo):
    """Pacientes ativos e com cadastro completo, no escopo."""
    qs = Patient.objects.filter(
        tenant_id=escopo.tenant_id, status=PatientStatus.ACTIVE,
        registration_stage=RegistrationStage.COMPLETE,
    )
    if escopo.medico is not None:
        atendidos, marcados = _ids_do_medico(escopo.tenant_id, escopo.medico)
        qs = qs.filter(Q(id__in=atendidos) | Q(id__in=marcados))
    return qs


def _atendimentos_do_periodo(escopo):
    qs = Encounter.objects.filter(
        tenant_id=escopo.tenant_id, status=EncounterStatus.FINALIZED,
        occurred_at__date__gte=escopo.inicio, occurred_at__date__lte=escopo.fim,
    )
    if escopo.medico is not None:
        qs = qs.filter(physician_membership=escopo.medico)
    return qs


def _primeiras_consultas(escopo):
    """A data da primeira consulta finalizada de cada paciente, no escopo.

    No escopo de um médico, a primeira **com ele**: "paciente novo" para o
    médico é quem ele atendeu pela primeira vez, ainda que já viesse à
    clínica com um colega.
    """
    qs = Encounter.objects.filter(tenant_id=escopo.tenant_id, status=EncounterStatus.FINALIZED)
    if escopo.medico is not None:
        qs = qs.filter(physician_membership=escopo.medico)
    return qs.values('patient_id').annotate(primeira=Min('occurred_at'))


# ------------------------------------------------------------------ números

def resumo(escopo):
    from . import patients as indicadores

    periodo = _atendimentos_do_periodo(escopo)
    novos = sum(
        1 for linha in _primeiras_consultas(escopo)
        if escopo.inicio <= timezone.localtime(linha['primeira']).date() <= escopo.fim
    )
    falta = indicadores.no_show_rate(
        escopo.tenant_id, escopo.inicio, escopo.fim, physician_membership=escopo.medico,
    )
    return {
        'carteira': carteira(escopo).count(),
        'atendimentos': periodo.count(),
        'pacientes_atendidos': periodo.values('patient_id').distinct().count(),
        'novos': novos,
        'falta': falta,
        'mailing': contatos_com_consentimento(escopo).count(),
    }


def _meses(inicio, fim):
    meses = []
    ano, mes = inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        meses.append(datetime.date(ano, mes, 1))
        mes += 1
        if mes > 12:
            mes, ano = 1, ano + 1
    return meses[-MAX_MESES:]


ROTULO_MES = ('jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez')


def mensal(escopo):
    """Atendimentos finalizados e pacientes novos por mês do período.

    `TruncMonth` corta no fuso ativo (São Paulo): o atendimento das 22h do
    último dia do mês fica no mês dele, e não no seguinte, como ficaria em
    UTC.
    """
    meses = _meses(escopo.inicio, escopo.fim)
    por_mes = Counter({
        linha['mes'].date() if hasattr(linha['mes'], 'date') else linha['mes']: linha['n']
        for linha in _atendimentos_do_periodo(escopo)
        .annotate(mes=TruncMonth('occurred_at')).values('mes').annotate(n=Count('id'))
    })
    novos = Counter()
    for linha in _primeiras_consultas(escopo):
        dia = timezone.localtime(linha['primeira']).date()
        if escopo.inicio <= dia <= escopo.fim:
            novos[dia.replace(day=1)] += 1
    linhas = [
        {
            'mes': mes, 'rotulo': f'{ROTULO_MES[mes.month - 1]}/{mes.strftime("%y")}',
            'atendimentos': por_mes.get(mes, 0), 'novos': novos.get(mes, 0),
        }
        for mes in meses
    ]
    # Altura de cada coluna relativa ao maior mês da própria série: são duas
    # séries em dois gráficos, e não um gráfico de dois eixos.
    for serie in ('atendimentos', 'novos'):
        maior = max((l[serie] for l in linhas), default=0) or 1
        for linha in linhas:
            linha[f'alt_{serie}'] = round(100 * linha[serie] / maior, 1)
    return linhas


def _com_percentual(linhas):
    total = sum(linha['n'] for linha in linhas) or 0
    maior = max((linha['n'] for linha in linhas), default=0) or 1
    for linha in linhas:
        linha['pct'] = round(100 * linha['n'] / total, 1) if total else 0
        linha['largura'] = round(100 * linha['n'] / maior, 1)
    return linhas


def idade(escopo):
    """Faixas etárias na data final do período, e a mediana.

    O ano de nascimento estimado conta (com a precisão que tem: a diferença
    de anos); quem não tem nem isso fica numa linha própria, fora da
    mediana — misturar "sem data" com zero puxaria a mediana para baixo.
    """
    ref = escopo.fim
    idades, sem_data = [], 0
    for nascimento, estimado in carteira(escopo).values_list('birth_date', 'estimated_birth_year'):
        if nascimento:
            anos = ref.year - nascimento.year - ((ref.month, ref.day) < (nascimento.month, nascimento.day))
        elif estimado:
            anos = ref.year - estimado
        else:
            sem_data += 1
            continue
        idades.append(max(anos, 0))
    linhas = [
        {'rotulo': rotulo, 'n': sum(1 for a in idades if de <= a <= ate)}
        for de, ate, rotulo in FAIXAS_ETARIAS
    ]
    if sem_data:
        linhas.append({'rotulo': 'Sem data de nascimento', 'n': sem_data})
    idades.sort()
    mediana = None
    if idades:
        meio = len(idades) // 2
        mediana = idades[meio] if len(idades) % 2 else (idades[meio - 1] + idades[meio]) / 2
    return {'linhas': _com_percentual(linhas), 'mediana': mediana, 'n': len(idades)}


def _por_escolha(qs, campo, choices, vazio='Não informado'):
    rotulos = dict(choices)
    contagem = Counter()
    for valor in qs.values_list(campo, flat=True):
        contagem[rotulos.get(valor, vazio) if valor else vazio] += 1
    return _com_percentual([{'rotulo': r, 'n': n} for r, n in contagem.most_common()])


def sexo(escopo):
    return _por_escolha(carteira(escopo), 'sex_at_registration', SexAtRegistration.choices)


def origem(escopo):
    return _por_escolha(carteira(escopo), 'referral_source', ReferralSource.choices)


def pagamento(escopo):
    return _por_escolha(carteira(escopo), 'payment_category', PaymentCategory.choices)


def uf(escopo):
    contagem = Counter(
        (valor or '').upper() or 'Não informado'
        for valor in carteira(escopo).values_list('state', flat=True)
    )
    return _com_percentual([{'rotulo': r, 'n': n} for r, n in contagem.most_common()])


def municipio(escopo, limite=None):
    """Municípios com a regra das células pequenas. `limite=None` traz todos."""
    contagem = Counter()
    for cidade, estado in carteira(escopo).values_list('city', 'state'):
        cidade = (cidade or '').strip()
        if not cidade:
            contagem['Não informado'] += 1
        else:
            contagem[f'{cidade.title()}/{(estado or "").upper()}'.rstrip('/')] += 1
    visiveis, outros = [], 0
    for rotulo, n in contagem.most_common():
        if rotulo != 'Não informado' and n < SMALL_CELL_THRESHOLD:
            outros += n
        else:
            visiveis.append({'rotulo': rotulo, 'n': n})
    if limite is not None and len(visiveis) > limite:
        outros += sum(linha['n'] for linha in visiveis[limite:])
        visiveis = visiveis[:limite]
    if outros:
        visiveis.append({'rotulo': f'Outros municípios (menos de {SMALL_CELL_THRESHOLD} pacientes cada)', 'n': outros})
    return _com_percentual(visiveis)


def convenios(escopo, limite=None):
    """Convênio vigente na data final, um por paciente e plano."""
    ref = escopo.fim
    linhas = (
        PatientCoverage.objects.filter(
            tenant_id=escopo.tenant_id, patient__in=carteira(escopo),
        )
        .filter(Q(starts_on__isnull=True) | Q(starts_on__lte=ref))
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=ref))
        .values('plan__insurer__name', 'plan__name')
        .annotate(n=Count('patient_id', distinct=True))
        .order_by('-n')
    )
    resultado = [
        {'rotulo': f'{l["plan__insurer__name"]} — {l["plan__name"]}', 'n': l['n']} for l in linhas
    ]
    if limite is not None and len(resultado) > limite:
        resto = sum(l['n'] for l in resultado[limite:])
        resultado = resultado[:limite] + [{'rotulo': 'Outros convênios', 'n': resto}]
    return _com_percentual(resultado)


def diagnosticos(escopo, limite=None):
    """Pacientes distintos por CID no período, confirmados e suspeitos à parte.

    Vale a **última palavra** sobre cada código, por paciente, dentro do
    período — a regra de `clinical/por_cid.py`: a hipótese levantada numa
    consulta e refutada na seguinte não conta como suspeita. O refutado não
    entra em série nenhuma. Confirmado e suspeito nunca se somam.

    Devolve `None` sem `READ_CLINICAL`: quem não abre prontuário não vê a
    distribuição de diagnósticos, e a tela explica por quê.
    """
    if not escopo.clinico:
        return None
    qs = EncounterDiagnosis.objects.filter(
        tenant_id=escopo.tenant_id, encounter__status=EncounterStatus.FINALIZED,
        encounter__occurred_at__date__gte=escopo.inicio, encounter__occurred_at__date__lte=escopo.fim,
    ).exclude(code_snapshot='')
    if escopo.medico is not None:
        qs = qs.filter(encounter__physician_membership=escopo.medico)
    ultima = {}
    descricao = {}
    for paciente, codigo, certeza, texto in qs.order_by('encounter__occurred_at', 'rank').values_list(
        'encounter__patient_id', 'code_snapshot', 'certainty', 'description_snapshot',
    ):
        codigo = codigo.strip().upper()
        ultima[(paciente, codigo)] = certeza
        if texto and codigo not in descricao:
            descricao[codigo] = texto.strip()[:160]
    series = {}
    for certeza in (DiagnosisCertainty.CONFIRMED, DiagnosisCertainty.SUSPECTED):
        contagem = Counter(codigo for (_, codigo), c in ultima.items() if c == certeza)
        linhas = [
            {'codigo': codigo, 'rotulo': f'{codigo} — {descricao.get(codigo, "")}'.rstrip(' —'), 'n': n}
            for codigo, n in contagem.most_common()
        ]
        if limite is not None:
            linhas = linhas[:limite]
        series[certeza] = _com_percentual(linhas)
    return {
        'confirmados': series[DiagnosisCertainty.CONFIRMED],
        'suspeitos': series[DiagnosisCertainty.SUSPECTED],
    }


# ------------------------------------------------------------------ mailing

def contatos_com_consentimento(escopo):
    """Os contatos que aceitam comunicação em massa, no escopo.

    A mesma regra das campanhas (`communications.marketing.eligible_contacts`),
    reaproveitada e não reescrita: consentimento dado e não revogado,
    contato válido, e-mail preenchido e paciente ativo. A lista do mailing
    externo não pode ser mais larga que a das campanhas do próprio sistema.
    """
    from communications.marketing import eligible_contacts

    qs = eligible_contacts(escopo.tenant_id)
    if escopo.medico is not None:
        qs = qs.filter(patient__in=carteira(escopo))
    return qs


MAILING_COLUNAS = ['nome', 'email', 'consentimento_em', 'descadastro_url']


def _escopo_do_worker(tenant_id, medico):
    medico_obj = None
    if medico:
        medico_obj = Membership.objects.filter(
            tenant_id=tenant_id, id=medico, roles__contains=[Role.DOCTOR],
        ).first()
    hoje = timezone.localdate()
    return Escopo(
        tenant_id=tenant_id, membership_id=None, medico=medico_obj, ve_clinica_inteira=True,
        clinico=False, pode_exportar_mailing=True, inicio=hoje, fim=hoje, periodo='',
    )


def mailing_count(tenant_id, medico='', declaracao=None):
    escopo = _escopo_do_worker(tenant_id, medico)
    if medico and escopo.medico is None:
        return 0
    return contatos_com_consentimento(escopo).count()


def mailing_rows(tenant_id, medico='', declaracao=None):
    """Uma linha por endereço de e-mail, com o link de descadastro dele.

    Um endereço só uma vez, sem diferença de caixa: dois contatos do mesmo
    paciente com o mesmo e-mail (a regra de `check_um_envio_por_endereco`)
    viram uma linha. Fica a primeira, que é a do contato mais antigo.

    O **link de descadastro vai junto** porque a revogação tem de ser tão
    fácil quanto o consentimento (LGPD, art. 8º, §5º) e tem de voltar para
    cá: um descadastro feito só na ferramenta externa não chega ao cadastro,
    e a próxima campanha do próprio sistema escreveria de novo para quem
    pediu para parar. A ferramenta põe o link de cada linha na mensagem.

    Mínimo necessário (art. 6º, III): nome do contato e e-mail. Nem o nome
    do paciente, nem telefone, nem nada clínico — constar de uma lista de
    clínica de neurologia já é dado sensível.
    """
    from communications.marketing import unsubscribe_url

    escopo = _escopo_do_worker(tenant_id, medico)
    if medico and escopo.medico is None:
        return []
    vistos, linhas = set(), []
    # Pela criação, e não pelo id: o id é UUID, e "o primeiro" pela ordem
    # dele seria um contato qualquer a cada exportação.
    for contato in contatos_com_consentimento(escopo).order_by('created_at', 'id'):
        chave = contato.email.strip().lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        linhas.append({
            'nome': contato.name,
            'email': contato.email.strip(),
            'consentimento_em': timezone.localtime(contato.marketing_opt_in_at).date().isoformat(),
            'descadastro_url': unsubscribe_url(contato),
        })
    return linhas


# --------------------------------------------------------------- CSV da tela

#: As tabelas que a tela oferece em CSV. Lista fechada: o nome vem da URL.
SECOES_CSV = {
    'mensal': ('Mês', 'atendimentos e pacientes novos por mês'),
    'idade': ('Faixa etária', 'pacientes por faixa etária'),
    'sexo': ('Sexo', 'pacientes por sexo'),
    'uf': ('UF', 'pacientes por estado'),
    'municipio': ('Município', 'pacientes por município'),
    'origem': ('Como chegou', 'pacientes por origem'),
    'pagamento': ('Forma de pagamento', 'pacientes por forma de pagamento'),
    'convenios': ('Convênio', 'pacientes por convênio'),
    'cid': ('CID', 'pacientes por diagnóstico'),
}


def linhas_csv(escopo, secao):
    """As linhas de uma tabela, completas (sem o corte do ranking da tela)."""
    if secao == 'mensal':
        return ['mes', 'atendimentos', 'pacientes_novos'], [
            {'mes': m['mes'].strftime('%Y-%m'), 'atendimentos': m['atendimentos'], 'pacientes_novos': m['novos']}
            for m in mensal(escopo)
        ]
    if secao == 'cid':
        dados = diagnosticos(escopo)
        if dados is None:
            return None
        linhas = [
            {'certeza': rotulo, 'cid': l['codigo'], 'descricao': l['rotulo'], 'pacientes': l['n']}
            for rotulo, serie in (('confirmado', dados['confirmados']), ('suspeita', dados['suspeitos']))
            for l in serie
        ]
        return ['certeza', 'cid', 'descricao', 'pacientes'], linhas
    funcoes = {
        'idade': lambda e: idade(e)['linhas'], 'sexo': sexo, 'uf': uf, 'municipio': municipio,
        'origem': origem, 'pagamento': pagamento, 'convenios': convenios,
    }
    if secao not in funcoes:
        return None
    return ['categoria', 'pacientes', 'percentual'], [
        {'categoria': l['rotulo'], 'pacientes': l['n'], 'percentual': l['pct']} for l in funcoes[secao](escopo)
    ]
