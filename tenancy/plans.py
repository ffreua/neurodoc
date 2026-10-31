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

#: Meses no ano. O total de um ano **deriva** do mensal de cada
#: periodicidade: dois números escritos à mão divergem na primeira mudança
#: de preço, e a página passa a prometer uma conta que não fecha.
MESES_NO_ANO = 12


class Periodicidade(models.TextChoices):
    """De quanto em quanto tempo a clínica paga — dentro do contrato de 12 meses.

    O contrato de adesão fixa a vigência em 12 meses e o valor "anual e
    devido integralmente na contratação, **salvo condição comercial
    expressamente registrada**" (`tenancy/contract.py`, versão 1.2). Pagar
    por semestre ou por trimestre é essa condição: ela vai no convite e fica
    gravada no aceite (`ContractAcceptance.periodicidade`). Um contrato de
    seis ou três meses seria outra coisa — mudaria a cláusula de vigência,
    e redação de contrato passa pela advogada.
    """

    ANUAL = 'anual', 'Anual'
    SEMESTRAL = 'semestral', 'Semestral'
    TRIMESTRAL = 'trimestral', 'Trimestral'


#: Decidido em 2026-10-30: o preço cheio é o mensal do plano; o anual tem
#: 20% de desconto **de lançamento**, o semestral 5%, e o trimestral paga o
#: preço cheio. O desconto existe **só** na periodicidade em que está
#: escrito — a página não pode dar a entender 20% para quem paga por
#: trimestre.
#:
#: `meses` é quantos meses cada pagamento cobre; `lancamento` marca o
#: desconto que é promoção (e que um dia acaba), para a tela dizê-lo.
PERIODICIDADES = {
    Periodicidade.ANUAL: {'meses': 12, 'desconto': 20, 'lancamento': True,
                          'por': 'por ano', 'pagamento': 'pagamento único anual'},
    Periodicidade.SEMESTRAL: {'meses': 6, 'desconto': 5, 'lancamento': False,
                              'por': 'por semestre', 'pagamento': '2 pagamentos semestrais'},
    Periodicidade.TRIMESTRAL: {'meses': 3, 'desconto': 0, 'lancamento': False,
                               'por': 'por trimestre', 'pagamento': '4 pagamentos trimestrais'},
}

#: A primeira que a vitrine mostra, e a do convite que não disser outra.
PERIODICIDADE_PADRAO = Periodicidade.ANUAL


def com_desconto(centavos, desconto):
    """O mensal com o desconto, em centavos, arredondado meio para cima.

    Em centavos e com arredondamento explícito, porque vai impresso numa
    página pública e num contrato: `float` aqui produziria `R$ 80,74999...`
    num dia qualquer. O total de cada pagamento e o do ano saem **deste**
    mensal multiplicado pelos meses — nunca de um segundo arredondamento —,
    para "R$ 80,75 por mês" e "R$ 484,50 por semestre" fecharem a conta que
    o leitor faz com o celular na mão.
    """
    if not centavos or not desconto:
        return centavos
    return (int(centavos) * (100 - int(desconto)) + 50) // 100


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
        'sms': False,
        'tiss': False,
        # `price_monthly` em centavos. Zero é grátis; `None` é "não há
        # preço de tabela", que é coisa diferente e só o Personalizado tem.
        'price_monthly': 0,
        'summary': 'Para o consultório solo e para quem está montando a própria '
                   'agenda. Comece hoje, sem falar com ninguém.',
        'features': [
            'Roteiro de exame neurológico completo, com as 387 verificações',
            'Escalas pontuadas e prontuário com guarda de vinte anos',
            'Receita e laudo assinados, com verificação pública por QR',
            'Avisos ao paciente por e-mail, pelo NeuroDoc ou pelo servidor da sua clínica',
            'Campanhas por e-mail com consentimento, com o servidor de e-mail da clínica',
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
        'sms': True,
        'tiss': False,
        # Preço cheio, por mês (2026-10-30). O desconto de cada
        # periodicidade sai de `PERIODICIDADES`, nunca escrito aqui.
        'price_monthly': 8500,
        'summary': 'Para o consultório que cresceu: dois médicos, convênios e '
                   'dinheiro entrando por mais de uma porta.',
        'features': [
            'Tudo do Gratuito',
            'Dois médicos, cada um com a própria grade de horários',
            'Lembrete de consulta por SMS, e código por SMS no acesso a documento',
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
        'sms': True,
        'tiss': True,
        'price_monthly': 17500,
        'summary': 'Para a clínica consolidada, com equipe multiprofissional e '
                   'agenda cheia nos cinco dias.',
        'features': [
            'Tudo do Básico',
            'Cinco médicos, secretaria e gestão, cada papel com o seu acesso',
            'IA como copiloto do registro, sempre com revisão médica',
            'Faturamento de convênio TISS: guias de Consulta e SP/SADT e lotes XML, '
            'em todas as versões do padrão da ANS',
            'Agenda de exames por equipamento: EEG, ENMG e polissonografia',
            'Indicadores de produtividade e faturamento, com exportação',
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
        'sms': True,
        'tiss': True,
        # Aqui `None` não é grátis: é "não há preço de tabela". A tela
        # precisa dizer isso, e não estampar um zero.
        'price_monthly': None,
        'summary': 'Para serviço de neurologia de grande porte, clínica cirúrgica '
                   'e hospital-dia — onde o padrão não serve.',
        'features': [
            'Tudo do Completo, inclusive o faturamento TISS e a agenda de exames',
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

#: Promoção **permanente** para quem está começando (decidida em 2026-10-31):
#: residentes de neurologia e neurologistas com até 2 anos de formados pagam
#: metade do preço cheio nos planos Básico e Completo, no pagamento anual.
#:
#: Os 50% são sobre o **preço cheio** e **no lugar** dos 20% de lançamento —
#: não somados a eles. Somar daria 60% num desconto que a página anuncia
#: como 50%, e a conta que o leitor faz não fecharia com a da tela.
#:
#: Só no anual, e por isso o seletor de forma de pagamento não a mostra nas
#: outras: a mesma regra de `PERIODICIDADES`, desconto só onde está escrito.
#: `permanente` existe para a tela não chamá-la de lançamento — esta não
#: acaba, e dizer o contrário espantaria quem ainda vai entrar na residência.
PROMOCAO_INICIO_DE_CARREIRA = {
    'desconto': 50,
    'planos': (PlanCode.BASIC, PlanCode.COMPLETE),
    'periodicidade': Periodicidade.ANUAL,
    'permanente': True,
    'titulo': 'Residentes e recém-formados pagam metade',
    'publico': 'residentes de neurologia e neurologistas com até 2 anos de formados',
    'comprovacao': 'declaração do programa de residência ou certificado de conclusão '
                   'da residência, apresentado ao contratar',
}


def preco_inicio_de_carreira(code):
    """O preço do plano na promoção de início de carreira, já formatado.

    `None` para plano fora da promoção. Derivado do preço cheio por
    `com_desconto`, como o das periodicidades — nenhum número escrito à mão.
    """
    promo = PROMOCAO_INICIO_DE_CARREIRA
    if code not in promo['planos']:
        return None
    cheio = plan_config(code).get('price_monthly')
    if not cheio:
        return None
    mensal = com_desconto(cheio, promo['desconto'])
    return {
        'code': str(code), 'label': PLANS[code]['label'], 'desconto': promo['desconto'],
        'mensal': brl(mensal), 'ano': brl(mensal * MESES_NO_ANO),
        'cheio': brl(cheio), 'cheio_ano': brl(cheio * MESES_NO_ANO),
        'economia_ano': brl((cheio - mensal) * MESES_NO_ANO),
        'mensal_centavos': mensal, 'ano_centavos': mensal * MESES_NO_ANO,
    }


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


def has_sms(code):
    """Se o plano inclui o envio de SMS.

    Mesmo desenho de `has_clinical_ai`, e pela mesma razao: SMS custa
    dinheiro por mensagem, e a clinica que nao configurou chave propria
    gasta a **da instalacao** -- quem hospeda o sistema paga a conta de
    quem usa. A IA ja era recurso de plano; o SMS nao era, e uma clinica no
    Gratuito, que nao paga nada, consumia os creditos de quem hospeda. O
    sintoma chega como "os lembretes pararam de sair", sem dizer por que.

    Corta no Gratuito e so nele. Do Basico para cima o SMS entra no
    pacote, e a linha de venda daquele plano passou a dize-lo -- que e o
    acoplamento que o cabecalho deste modulo existe para manter: o que se
    anuncia e o que o servidor cumpre moram no mesmo arquivo.

    O corte e por plano e vale **inclusive** para a clinica do Gratuito que
    trouxe a propria chave. Nao e descuido: e a mesma regra do
    `clinical_ai`, e um recurso que aparece ou some conforme a clinica
    cadastrou credencial seria impossivel de explicar na pagina de precos.

    `.get` com `False` pela razao de sempre: plano sem a chave fica **sem**
    o recurso. Errar para o lado do menor direito aparece como "recurso nao
    disponivel"; errar para o outro gasta credito sem contrato.
    """
    return plan_config(code).get('sms', False)


def has_tiss(code):
    """O plano inclui o faturamento TISS (guias de convênio e lotes em XML).

    Completo e Personalizado. É uma das **três** chaves do módulo, e a única
    comercial: as outras são `Tenant.tiss_liberado` (a clínica entra quando
    a liberação gradual chega a ela) e `InstallationSettings.tiss_ativo` (o
    freio da instalação inteira). Ver `docs/tiss/REVISAO_SPRINT1.md` §4.1.

    Ausente vale `False`, e plano desconhecido cai no Gratuito
    (`plan_config`): na dúvida, o módulo não abre.
    """
    return plan_config(code).get('tiss', False)


def preco_na_periodicidade(code, periodicidade=PERIODICIDADE_PADRAO):
    """O que o plano custa numa periodicidade, em centavos. `None` se não há preço.

    `mensal` é o equivalente por mês, `pagamento` o valor de cada cobrança
    (12, 6 ou 3 meses), `ano` o total de doze meses. Grátis devolve zeros.
    """
    cheio = plan_config(code).get('price_monthly')
    if cheio is None:
        return None
    regra = PERIODICIDADES[Periodicidade(periodicidade)]
    mensal = com_desconto(cheio, regra['desconto'])
    return {
        'cheio': cheio, 'mensal': mensal, 'pagamento': mensal * regra['meses'],
        'ano': mensal * MESES_NO_ANO, 'economia_ano': (cheio - mensal) * MESES_NO_ANO,
        'meses': regra['meses'], 'desconto': regra['desconto'],
    }


def pricing(code):
    """O preço de um plano, já formatado, para a vitrine.

    Três estados, e a tela precisa distinguir os três: grátis (`0`), com
    preço (as três periodicidades, em `periodos`) e sem preço (`None` — o
    Personalizado, combinado caso a caso).

    Em cada periodicidade: o mensal equivalente, o valor de cada pagamento
    e **sempre** o total de um ano, que é o número que permite comparar as
    três. Tudo derivado do preço cheio por `preco_na_periodicidade`.

    `monthly` e `annual` (os da periodicidade padrão, a anual) continuam
    existindo para quem precisa de um número só: o menu do formulário, o
    JSON-LD.
    """
    centavos = plan_config(code).get('price_monthly')
    if centavos is None:
        return {
            'free': False, 'quoted': False, 'promo': False, 'periodos': [],
            'monthly': '', 'annual': '', 'note': 'Valores de acordo com o que for fechado.',
        }
    if centavos == 0:
        return {
            'free': True, 'quoted': True, 'promo': False, 'periodos': [],
            'monthly': 'Grátis', 'annual': '',
            'note': 'Sem cobrança e sem prazo. É por onde dá para conhecer o sistema '
                    'antes de contratar.',
        }
    periodos = []
    for codigo, regra in PERIODICIDADES.items():
        v = preco_na_periodicidade(code, codigo)
        periodos.append({
            'code': str(codigo), 'label': codigo.label, 'desconto': v['desconto'],
            'lancamento': regra['lancamento'], 'por': regra['por'],
            'pagamento_rotulo': regra['pagamento'],
            'mensal': brl(v['mensal']), 'pagamento': brl(v['pagamento']), 'ano': brl(v['ano']),
            'cheio': brl(v['cheio']), 'cheio_ano': brl(v['cheio'] * MESES_NO_ANO),
            'economia_ano': brl(v['economia_ano']),
            'mensal_centavos': v['mensal'], 'ano_centavos': v['ano'],
        })
    padrao = next(p for p in periodos if p['code'] == PERIODICIDADE_PADRAO)
    return {
        'free': False, 'quoted': True, 'promo': any(p['desconto'] for p in periodos),
        'periodos': periodos, 'full_monthly': brl(centavos),
        'monthly': padrao['mensal'], 'annual': padrao['ano'], 'discount': padrao['desconto'],
        'note': 'Contrato de 12 meses, pago por ano, semestre ou trimestre.',
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
            rotulo += f' — a partir de {preco["monthly"]}/mês no anual'
        else:
            rotulo += ' — valores a combinar'
        opcoes.append((str(code), rotulo))
    return opcoes
