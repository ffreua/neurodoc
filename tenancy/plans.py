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

#: Desconto de lancamento, em pontos percentuais.
#:
#: O que esta escrito em `price_monthly` e o que a clinica **paga**. O
#: preco de tabela -- o valor riscado -- e derivado daqui, e nao um
#: segundo numero guardado a mao.
#:
#: A direcao importa e foi escolhida: deriva-se o **caro a partir do
#: barato**, porque o barato e o que sera cobrado de fato e o unico que
#: aparece na fatura. O contrario (guardar a tabela e calcular o cobrado)
#: faria o valor da fatura depender de arredondamento.
#:
#: E o percentual e a fonte, e nao consequencia: a pagina **anuncia** "20%
#: de desconto", entao esse numero precisa fechar com a subtracao que o
#: leitor pode fazer na tela. Guardar o preco de tabela e chamar a
#: diferenca de 20% seria a forma de anunciar um desconto que nao existe --
#: um preco de tabela 20% mais caro que o cobrado e, visto do outro lado,
#: 16,7% de desconto, e nao 20%.
#:
#: Zero desliga a promocao em todo lugar: some o valor riscado, some o
#: selo, e o preco passa a ser so o preco.
DESCONTO_PROMOCIONAL = 20


def sem_desconto(centavos):
    """O preco de tabela do qual `centavos` e o valor ja com desconto.

    Em centavos e com arredondamento explicito (meio para cima), porque o
    resultado vai impresso numa pagina publica: `float` aqui produziria
    `R$ 197,49999...` num dia qualquer, dependendo do preco.
    """
    if not centavos or not DESCONTO_PROMOCIONAL:
        return centavos
    restante = 100 - DESCONTO_PROMOCIONAL
    return (int(centavos) * 100 + restante // 2) // restante


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
        'clinical_ai': False,
        # `price_monthly` em centavos. Zero é grátis; `None` é "não há
        # preço de tabela", que é coisa diferente e só o Personalizado tem.
        'price_monthly': 0,
        'summary': 'Para o consultório solo e para quem está montando a própria '
                   'agenda. Comece hoje, sem falar com ninguém.',
        'features': [
            'Roteiro de exame neurológico completo, com as 387 verificações',
            'Escalas pontuadas e prontuário com guarda de vinte anos',
            'Receita e laudo assinados, com verificação pública por QR',
            'Sem cartão de crédito, sem prazo e sem letra miúda',
        ],
        'highlight': False,
        'contact_only': False,
    },
    PlanCode.BASIC: {
        'label': 'Básico',
        'max_patients': 3500,
        'max_doctors': 2,
        'clinical_ai': False,
        'price_monthly': 15800,
        'summary': 'Para o consultório que cresceu: dois médicos, convênios e '
                   'dinheiro entrando por mais de uma porta.',
        'features': [
            'Tudo do Gratuito',
            'Dois médicos, cada um com a própria grade de horários',
            'Honorários com vigência, repasses e recebíveis por convênio',
            'Portal do paciente: renovação de receita sem ligar para a recepção',
        ],
        'highlight': False,
        'contact_only': False,
    },
    PlanCode.COMPLETE: {
        'label': 'Completo',
        'max_patients': 12000,
        'max_doctors': 5,
        'clinical_ai': True,
        'price_monthly': 26200,
        'summary': 'Para a clínica consolidada, com equipe multiprofissional e '
                   'agenda cheia nos cinco dias.',
        'features': [
            'Tudo do Básico',
            'Cinco médicos, secretaria e gestão, cada papel com o seu acesso',
            'IA como copiloto do registro, sempre com revisão médica',
            'Indicadores de produtividade e faturamento, com exportação',
            'Campanhas e avisos em massa, com consentimento registrado',
        ],
        'highlight': True,
        'contact_only': False,
    },
    PlanCode.CUSTOM: {
        'label': 'Personalizado',
        # None é ilimitado. Ver o cabeçalho deste módulo.
        'max_patients': None,
        'max_doctors': None,
        'clinical_ai': True,
        # Aqui `None` não é grátis: é "não há preço de tabela". A tela
        # precisa dizer isso, e não estampar um zero.
        'price_monthly': None,
        'summary': 'Para serviço de neurologia de grande porte, clínica cirúrgica '
                   'e hospital-dia — onde o padrão não serve.',
        'features': [
            'Pacientes e médicos sem teto: o limite é o que for combinado',
            'Condições comerciais e de implantação desenhadas com a sua equipe',
            'Conversa direta com quem desenvolve, não com um canal de suporte',
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


def has_clinical_ai(code):
    """Se o plano inclui o apoio clínico por IA.

    Existe porque a linha de venda existia sozinha. `features` já anunciava
    "IA como copiloto do registro" **só** no Completo, e o produto não
    cobrava isso em lugar nenhum: uma clínica no Gratuito tinha a IA
    inteira. Era exatamente a divergência que o cabeçalho deste módulo diz
    que este acoplamento impede — texto de venda e o que o servidor cumpre
    no mesmo arquivo —, e ela estava aqui dentro.

    `.get` com `False`, e não `[...]`: plano sem a chave (código
    desconhecido, plano novo escrito pela metade) fica **sem** IA. É a
    mesma direção de erro do `plan_config` logo acima — errar para o lado
    do menor direito aparece como "recurso não disponível, fale conosco",
    e errar para o outro lado gasta a chave da instalação sem contrato.
    """
    return plan_config(code).get('clinical_ai', False)


def pricing(code):
    """O preço de um plano, já formatado, nos três jeitos que a tela usa.

    O anual **deriva** do mensal (`MESES_NO_ANO`), e não é um segundo
    número escrito à mão: dois números independentes divergem na primeira
    mudança de preço, e a página passa a prometer uma conta que não fecha.

    Três estados, e a tela precisa distinguir os três:

    - grátis (`0`): não há cobrança;
    - com preço de tabela: mensal, anual e a equivalência;
    - sem preço de tabela (`None`): o Personalizado, combinado caso a caso.

    Quando há promoção (`DESCONTO_PROMOCIONAL`), o mesmo dicionário traz o
    preço **de tabela** — `list_monthly`, `list_annual` — e a economia no
    ano. Todos derivados do que se cobra, e não guardados ao lado dele:
    dois preços escritos à mão divergem na primeira mudança, e o valor
    riscado é justamente o que ninguém confere depois.
    """
    centavos = plan_config(code).get('price_monthly')
    if centavos is None:
        return {
            'free': False, 'quoted': False, 'promo': False,
            'monthly': '', 'annual': '', 'note': 'Valores de acordo com o que for fechado.',
        }
    if centavos == 0:
        return {
            'free': True, 'quoted': True, 'promo': False,
            'monthly': 'Grátis', 'annual': '',
            'note': 'Sem cobrança e sem prazo. É por onde dá para conhecer o sistema '
                    'antes de contratar.',
        }
    anual = centavos * MESES_NO_ANO
    tabela_mensal = sem_desconto(centavos)
    # O anual de tabela sai do mensal de tabela pelo mesmo caminho que o
    # anual cobrado sai do mensal cobrado. Dividir o anual cobrado
    # diretamente daria o mesmo numero quase sempre e um centavo de
    # diferenca quando nao desse -- e essa diferenca apareceria como "o
    # riscado nao bate com 12x o riscado" na unica tela que a mostra.
    tabela_anual = tabela_mensal * MESES_NO_ANO
    return {
        'free': False, 'quoted': True,
        'promo': bool(DESCONTO_PROMOCIONAL),
        'monthly': brl(centavos),
        'annual': brl(anual),
        'discount': DESCONTO_PROMOCIONAL,
        'list_monthly': brl(tabela_mensal),
        'list_annual': brl(tabela_anual),
        'saving_annual': brl(tabela_anual - anual),
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
