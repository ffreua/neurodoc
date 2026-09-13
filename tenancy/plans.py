"""Os planos do NeuroDoc: o que cada um dá, e quanto ele deixa crescer.

O catálogo fica **em código**, e não numa tabela do banco.

A razão é o que um plano é: o registro do que foi vendido a alguém. Numa
tabela, baixar o limite do Básico de 500 para 400 alteraria em silêncio o
direito de toda clínica já contratada, e não sobraria nada dizendo que
antes era outro. Em código, a mesma mudança é um commit — com data, autor
e a possibilidade de alguém perguntar por quê antes de ela valer.

O que varia por cliente **não** é o plano: é o desvio. A clínica que
negociou 1.200 pacientes recebe `patient_limit_override=1200` e continua
no Básico; criar um quinto plano para cada negociação faria o catálogo
crescer com o número de clientes.

`None` é ilimitado, em todo lugar deste módulo. Nunca um número grande:
`999999` é um limite que um dia alguém bate, e na véspera ninguém sabe
que ele existe.
"""

from django.db import models

#: Meses numa assinatura. Existe como constante porque o preco anual e o
#: mensal precisam **derivar um do outro**: dois numeros escritos a mao
#: divergem na primeira mudanca de preco, e a pagina passa a prometer uma
#: conta que nao fecha.
MESES_NO_ANO = 12


def brl(centavos):
    """Formata em reais, no formato brasileiro: `R$ 1.896,00`.

    Em centavos, e nao em float: `158.00 * 12` em ponto flutuante devolve
    `1895.9999999999998`, e preco e a ultima coisa que deve depender de
    arredondamento de binario.

    `None` e "nao ha preco de tabela" -- o Personalizado -- e nao zero.
    """
    if centavos is None:
        return ''
    inteiro, resto = divmod(int(centavos), 100)
    milhar = f'{inteiro:,}'.replace(',', '.')
    return f'R$ {milhar},{resto:02d}'


class PlanCode(models.TextChoices):
    FREE = 'free', 'Gratuito'
    BASIC = 'basic', 'Básico'
    COMPLETE = 'complete', 'Completo'
    CUSTOM = 'custom', 'Personalizado'


#: Limite de pacientes **ativos** e de médicos por plano.
#:
#: Pacientes ativos, e não todos os já cadastrados: arquivar libera vaga.
#: É coerente com o resto do produto, onde arquivar já tira o paciente da
#: carteira ativa e dos indicadores, e não pune quem mantém o cadastro
#: limpo. `tenancy.limits` é quem conta.
#:
#: O texto de venda mora aqui junto, e não no template, para a página
#: pública e o que o sistema cumpre não poderem divergir: anunciar "até
#: 500" numa tela enquanto o servidor corta em 400 é o defeito que este
#: acoplamento impede.
PLANS = {
    PlanCode.FREE: {
        'label': 'Gratuito',
        'max_patients': 50,
        'max_doctors': 1,
        # `price_monthly` em centavos. Zero é grátis; `None` é "não há
        # preço de tabela", que é coisa diferente e só o Personalizado tem.
        'price_monthly': 0,
        'summary': 'Para o consultório que está começando ou quer conhecer o sistema.',
        'features': [
            'Prontuário estruturado e roteiro de exame neurológico',
            'Agenda e cadastro de pacientes',
            'Documentos assinados com verificação pública',
            'Sem cartão de crédito, sem prazo para acabar',
        ],
        'highlight': False,
        'contact_only': False,
    },
    PlanCode.BASIC: {
        'label': 'Básico',
        'max_patients': 3500,
        'max_doctors': 2,
        'price_monthly': 15800,
        'summary': 'Para o consultório com dois médicos e carteira consolidada.',
        'features': [
            'Tudo do Gratuito',
            'Dois médicos com agenda própria',
            'Financeiro, convênios e tabela de honorários',
            'Portal de solicitações do paciente',
        ],
        'highlight': False,
        'contact_only': False,
    },
    PlanCode.COMPLETE: {
        'label': 'Completo',
        'max_patients': 12000,
        'max_doctors': 5,
        'price_monthly': 26200,
        'summary': 'Para a clínica com equipe e volume de atendimento consolidado.',
        'features': [
            'Tudo do Básico',
            'Cinco médicos',
            'Apoio de IA com revisão médica',
            'Relatórios e indicadores gerenciais',
            'Comunicação em massa com consentimento',
        ],
        'highlight': True,
        'contact_only': False,
    },
    PlanCode.CUSTOM: {
        'label': 'Personalizado',
        # None é ilimitado. Ver o cabeçalho deste módulo.
        'max_patients': None,
        'max_doctors': None,
        # Aqui `None` não é grátis: é "não há preço de tabela". A tela
        # precisa dizer isso, e não estampar um zero.
        'price_monthly': None,
        'summary': 'Para quem precisa de outro tamanho, ou de condições próprias.',
        'features': [
            'Limites combinados caso a caso',
            'Quantos médicos a clínica tiver',
            'Valores de acordo com o que for fechado',
        ],
        'highlight': False,
        'contact_only': True,
    },
}

#: Ordem em que os planos aparecem na página de vendas. Explícita, e não a
#: ordem do dicionário: a de cima é acidental, e quem acrescentar um plano
#: no meio do arquivo não deveria mudar a vitrine sem querer.
PUBLIC_ORDER = [PlanCode.FREE, PlanCode.BASIC, PlanCode.COMPLETE, PlanCode.CUSTOM]

#: Plano de quem chega sem convite que diga outra coisa.
DEFAULT_PLAN = PlanCode.FREE


def plan_config(code):
    """A configuração de um plano, ou a do plano padrão se o código não existe.

    Não levanta. Um código desconhecido gravado num tenant — por uma
    migração antiga, por um `.env` de outra instalação, por edição manual
    no admin — não pode derrubar toda tela que mostre o plano da clínica.
    Cair no plano padrão é o comportamento conservador: é o **menor**
    limite, então o erro aparece como "cadastro recusado, fale conosco" e
    não como acesso liberado acima do contratado.
    """
    return PLANS.get(code, PLANS[DEFAULT_PLAN])


def plan_label(code):
    return plan_config(code)['label']


def max_patients(code):
    """Limite de pacientes do plano. `None` é ilimitado."""
    return plan_config(code)['max_patients']


def max_doctors(code):
    """Limite de médicos do plano. `None` é ilimitado."""
    return plan_config(code)['max_doctors']


def pricing(code):
    """O preço de um plano, já formatado, nos três jeitos que a tela usa.

    O anual **deriva** do mensal (`MESES_NO_ANO`), e não é um segundo
    número escrito à mão: dois números independentes divergem na primeira
    mudança de preço, e a página passa a prometer uma conta que não fecha.

    Três estados, e a tela precisa distinguir os três:

    - grátis (`0`): não há cobrança;
    - com preço de tabela: mensal, anual e a equivalência;
    - sem preço de tabela (`None`): o Personalizado, combinado caso a caso.
    """
    centavos = plan_config(code).get('price_monthly')
    if centavos is None:
        return {
            'free': False, 'quoted': False,
            'monthly': '', 'annual': '', 'note': 'Valores de acordo com o que for fechado.',
        }
    if centavos == 0:
        return {
            'free': True, 'quoted': True,
            'monthly': 'Grátis', 'annual': '',
            'note': 'Sem cobrança e sem prazo. É por onde dá para conhecer o sistema '
                    'antes de contratar.',
        }
    return {
        'free': False, 'quoted': True,
        'monthly': brl(centavos),
        'annual': brl(centavos * MESES_NO_ANO),
        'note': 'Pagamento anual.',
    }


def public_plans():
    """Os planos da página de vendas, na ordem, já com código e preço."""
    return [
        dict(PLANS[code], code=str(code), price=pricing(code))
        for code in PUBLIC_ORDER
    ]


def plan_choices():
    """Opções para o menu do formulário de contato.

    Sai daqui, e não de uma lista escrita no formulário: acrescentar um
    plano deve aparecer no menu sem que ninguém precise lembrar de uma
    segunda lista. O rótulo carrega o preço porque é o que a pessoa acabou
    de ler nos cartões logo acima.
    """
    opcoes = [('', 'Selecione o plano de interesse')]
    for code in PUBLIC_ORDER:
        preco = pricing(code)
        rotulo = PLANS[code]['label']
        if preco['free']:
            rotulo += ' — grátis'
        elif preco['quoted']:
            rotulo += f' — {preco["monthly"]}/mês, pago anualmente'
        else:
            rotulo += ' — valores a combinar'
        opcoes.append((str(code), rotulo))
    return opcoes
