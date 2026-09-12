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
        'summary': 'Para o consultório que está começando ou quer conhecer o sistema.',
        'features': [
            'Prontuário estruturado e roteiro de exame neurológico',
            'Agenda e cadastro de pacientes',
            'Documentos assinados com verificação pública',
            'Sem cartão de crédito',
        ],
        'highlight': False,
        'contact_only': False,
    },
    PlanCode.BASIC: {
        'label': 'Básico',
        'max_patients': 500,
        'max_doctors': 2,
        'summary': 'Para o consultório com dois médicos e carteira em formação.',
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
        'max_patients': 3000,
        'max_doctors': 5,
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
        'summary': 'Para quem precisa de outro tamanho, ou de condições próprias.',
        'features': [
            'Limites combinados caso a caso',
            'Quantos médicos a clínica tiver',
            'Condições definidas em conversa',
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


def public_plans():
    """Os planos da página de vendas, na ordem, já com o código junto."""
    return [dict(PLANS[code], code=str(code)) for code in PUBLIC_ORDER]
