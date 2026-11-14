"""O aceite do contrato de adesão: registro, prazos e cópia ao contratante.

O texto mora em `tenancy/contract.py`; aqui fica o que acontece quando
alguém clica em "li e aceito". Três coisas, nesta ordem, e a ordem
importa:

1. **Grava o aceite**, dentro da mesma transação que cria a clínica. Se a
   criação falhar, o aceite some com ela; se o aceite falhar, a clínica
   não nasce. Uma organização sem contrato registrado é um problema que
   não tem conserto retroativo.
2. **Calcula os prazos e os grava.** Arrependimento e vencimento são
   termo de contrato, não configuração: mudar `PRAZO_ARREPENDIMENTO_DIAS`
   amanhã não pode encurtar o prazo de quem assinou ontem.
3. **Tenta mandar a cópia por e-mail.** Falhar aqui não desfaz nada —
   o aceite está gravado, e o console mostra que a cópia não saiu.
"""

import hashlib

from django.conf import settings
from django.utils import timezone

from . import contract
from .models import ContractAcceptance

#: Código de Defesa do Consumidor, art. 49. Sete dias **corridos**, e não
#: úteis: é assim que o artigo conta, e contar diferente a favor de quem
#: redigiu o contrato é exatamente o que torna a cláusula discutível.
PRAZO_ARREPENDIMENTO_DIAS = 7

#: Vigência de quem não tem período pago — o Gratuito, o Personalizado e a
#: degustação —, em meses. O plano pago vence pelo período escolhido (1.47,
#: `plans.meses_da_periodicidade`): 12, 6 ou 3 meses depois do aceite.
VIGENCIA_MESES = 12


def sha_do_texto():
    """SHA-256 do contrato como ele está agora.

    É o que transforma "versão 2026-09-20" em prova: a versão é um rótulo
    que alguém pode esquecer de trocar, o hash não.
    """
    return hashlib.sha256(contract.texto_simples().encode('utf-8')).hexdigest()


def somar_meses(momento, meses):
    """Mesmo dia, `meses` adiante. Dia que não existe vira o último do mês.

    `timedelta(days=…)` erraria por um dia a cada mês de 31 ou fevereiro no
    meio, e o vencimento de um contrato não pode andar sozinho. Quem assina
    em 31/08 por seis meses vence em 28/02 (ou 29/02) — a regra do Código
    Civil para prazos que caem em data inexistente. Vale também para o
    `datetime` consciente de fuso: só a data muda, a hora fica.
    """
    import calendar

    total = momento.month - 1 + meses
    ano, mes = momento.year + total // 12, total % 12 + 1
    return momento.replace(year=ano, month=mes,
                           day=min(momento.day, calendar.monthrange(ano, mes)[1]))


def _somar_um_ano(momento):
    """Mesma data, ano seguinte; 29/02 vira 28/02."""
    return somar_meses(momento, 12)


def meses_de_vigencia(plan, periodicidade=None):
    """Meses que o aceite vale: o período, no plano pago; 12 nos demais."""
    from .plans import meses_da_periodicidade

    if preco_do_pagamento_centavos(plan, periodicidade):
        return meses_da_periodicidade(periodicidade or 'anual')
    return VIGENCIA_MESES


def preco_anual_centavos(plan, periodicidade=None):
    """O que o plano custa em doze meses, na periodicidade. `None` quando é combinado.

    Sai de `tenancy/plans.py::preco_na_periodicidade`, a mesma conta da
    vitrine — um segundo cálculo aqui divergiria dela na primeira mudança
    de preço, e o contrato registraria um valor que a página nunca mostrou.
    """
    from .plans import PERIODICIDADE_PADRAO, preco_na_periodicidade

    valor = preco_na_periodicidade(plan, periodicidade or PERIODICIDADE_PADRAO)
    return None if valor is None else valor['ano']


def preco_do_pagamento_centavos(plan, periodicidade=None):
    """O valor de cada pagamento (ano, semestre ou trimestre). `None` se combinado."""
    from .plans import PERIODICIDADE_PADRAO, preco_na_periodicidade

    valor = preco_na_periodicidade(plan, periodicidade or PERIODICIDADE_PADRAO)
    return None if valor is None else valor['pagamento']


def registrar_aceite(tenant, user, plan, ip=None, user_agent='', versao=None,
                     quando=None, poderes_declarados=False, periodicidade=None,
                     degustacao_plano='', degustacao_ate=None):
    """Grava o aceite. Chamado de dentro da transação que cria a clínica.

    Guarda o texto inteiro, e não só o hash: a cláusula 2.3 exige que uma
    cópia do conteúdo aceito fique vinculada ao registro, e o hash prova
    que um texto é aquele texto sem devolver o texto.
    """
    agora = quando or timezone.now()
    return ContractAcceptance.objects.create(
        tenant=tenant,
        version=versao or contract.VERSAO,
        text_sha256=sha_do_texto(),
        text=contract.texto_simples(),
        plan=plan,
        price_annual_cents=preco_anual_centavos(plan, periodicidade),
        # A condição comercial da cláusula de pagamento: de quanto em quanto
        # tempo, e quanto em cada vez. Só tem sentido em plano com preço.
        periodicidade=(periodicidade or 'anual') if preco_anual_centavos(plan) else '',
        price_payment_cents=preco_do_pagamento_centavos(plan, periodicidade),
        # A degustação é condição comercial do aceite do Gratuito (1.35):
        # o que se provou e até quando, gravado no instante como o resto.
        degustacao_plano=degustacao_plano or '',
        degustacao_ate=degustacao_ate,
        representation_declared=bool(poderes_declarados),
        accepted_by=user,
        # Nome montado do primeiro e do ultimo, e nao de `get_full_name()`:
        # aquele devolve o e-mail quando nao ha nome, e o aceite passaria a
        # dizer que "Fulano <fulano@...>" se chama "fulano@...".
        accepted_name=f'{user.first_name} {user.last_name}'.strip()[:255],
        accepted_email=user.email,
        source_ip=ip,
        user_agent=(user_agent or '')[:255],
        withdrawal_deadline=agora + timezone.timedelta(days=PRAZO_ARREPENDIMENTO_DIAS),
        # O período pago (1.47): 3, 6 ou 12 meses. A degustação adere ao
        # Gratuito, que não tem preço, e fica nos 12 de sempre.
        expires_at=somar_meses(agora, meses_de_vigencia(
            '' if degustacao_plano else plan, periodicidade)),
    )


def _corpo(aceite):
    """A cópia que o contratante recebe.

    Começa pelos dados do aceite e só depois vem o contrato: quem abre
    este e-mail seis meses depois está procurando uma data ou um prazo, e
    não relendo dezoito cláusulas para encontrá-la.

    O corpo sai de `aceite.text`, a cópia gravada no aceite (cláusula
    2.3), e **não** do texto corrente: reenviar a via de um contrato
    antigo com a redação nova seria mandar à pessoa um documento que ela
    nunca aceitou. Aceite anterior à coluna, que não tem cópia, cai no
    texto corrente — com o aviso de que a versão pode ter mudado.
    """
    from .plans import brl, plan_label

    cabecalho = [
        'Este e-mail é a sua via do contrato de adesão ao NeuroDoc.',
        'Guarde-o: ele registra o que foi aceito, por quem e quando.',
        '',
        f'Clínica:            {aceite.tenant.trade_name or aceite.tenant.legal_name}',
        f'{aceite.tenant.documento_rotulo + ":":<20}{aceite.tenant.documento_formatado}',
        f'Plano contratado:   {plan_label(aceite.plan)}',
        # O preco do dia, e nao o de hoje: e a "condicao comercial" que a
        # clausula 2.2, "h" manda registrar, e ela nao acompanha reajuste.
        *([f'Período contratado: {aceite.get_periodicidade_display()} — '
           f'{brl(aceite.price_payment_cents)}, pagamento único, sem renovação automática']
          if aceite.price_payment_cents and aceite.periodicidade else
          ['Valor:              sem cobrança ou combinado à parte']),
        *([f'Condição comercial: degustação do plano {plan_label(aceite.degustacao_plano)} '
           f'até {(timezone.localtime(aceite.degustacao_ate) - timezone.timedelta(days=1)):%d/%m/%Y} '
           f'(último dia); depois, plano {plan_label(aceite.plan)}']
          if aceite.degustacao_plano and aceite.degustacao_ate else []),
        # Sem o nome entre parenteses quando ele nao existe: a conta recem
        # criada ainda nao tem nome, e a linha saia com o mesmo e-mail duas
        # vezes.
        f'Aceito por:         {aceite.accepted_name} <{aceite.accepted_email}>'
        if aceite.accepted_name else f'Aceito por:         {aceite.accepted_email}',
        f'Data e hora:        {timezone.localtime(aceite.created_at).strftime("%d/%m/%Y às %H:%M")}',
        f'Origem (IP):        {aceite.source_ip or "não registrado"}',
        f'Versão do contrato: {aceite.version}',
        f'Conferência:        SHA-256 {aceite.text_sha256}',
        f'Poderes declarados: '
        f'{"sim" if aceite.representation_declared else "não registrado"}',
        '',
        f'Arrependimento até: {timezone.localtime(aceite.withdrawal_deadline).strftime("%d/%m/%Y")}'
        f' ({PRAZO_ARREPENDIMENTO_DIAS} dias corridos)',
        f'Vencimento:         {timezone.localtime(aceite.expires_at).strftime("%d/%m/%Y")}',
        '',
        '-' * 70,
        '',
    ]
    if aceite.text:
        return '\n'.join(cabecalho) + aceite.text
    cabecalho[-1:] = [
        'ATENÇÃO: este aceite é anterior ao arquivamento da cópia contratual. '
        'O texto abaixo é o que está em vigor hoje e pode diferir do que foi '
        'aceito; a conferência acima identifica o texto original.',
        '',
    ]
    return '\n'.join(cabecalho) + contract.texto_simples()


def enviar_copia(aceite):
    """Manda a via ao contratante. Falha aqui não desfaz o aceite.

    Chamado **fora** da transação de criação da clínica, de propósito: o
    envio fala com um servidor de e-mail, e prender uma transação de banco
    esperando SMTP responder é como se seguram conexões até o pool acabar.
    """
    from communications.email import send_email

    try:
        send_email(
            aceite.accepted_email,
            f'Contrato de adesão NeuroDoc — via da {aceite.tenant.trade_name or aceite.tenant.legal_name}',
            _corpo(aceite),
            tenant_id=aceite.tenant_id,
        )
    except Exception as exc:                            # noqa: BLE001
        # Truncado como no lead: o corpo do erro de SMTP costuma trazer
        # endereço de servidor e usuário de autenticação.
        ContractAcceptance.objects.filter(id=aceite.id).update(email_error=str(exc)[:255])
        return False
    ContractAcceptance.objects.filter(id=aceite.id).update(
        emailed_at=timezone.now(), email_error='',
    )
    return True


def _documento_para_operacao(tenant):
    """O documento como vai à caixa de operação: o CPF sai mascarado.

    O CNPJ é público; o CPF é dado pessoal de quem contrata como pessoa
    física, e esta caixa é a dos pedidos de contato, lida por mais gente e
    guardada sem prazo. Quem opera precisa reconhecer a adesão, não o
    número — que está inteiro no console (revisão de 2026-11-02, C8).
    """
    if tenant.pessoa_fisica:
        d = tenant.cpf
        return f'***.{d[3:6]}.{d[6:9]}-**'
    return tenant.documento_formatado


def copia_para_operacao(aceite):
    """Avisa quem mantém a instalação que uma clínica aderiu.

    Vai para `LEADS_EMAIL`, a mesma caixa dos pedidos de contato e das
    mensagens de clínica. Sem o contrato inteiro: quem opera já tem o
    texto, e o que ele precisa saber é que existe mais uma adesão, de
    quem, em que plano.
    """
    from communications.email import send_email
    from .plans import plan_label

    try:
        send_email(
            settings.LEADS_EMAIL,
            f'[NeuroDoc] Nova adesão: {aceite.tenant.trade_name or aceite.tenant.legal_name}',
            '\n'.join([
                f'Clínica:  {aceite.tenant.legal_name} '
                f'({aceite.tenant.documento_rotulo} {_documento_para_operacao(aceite.tenant)})',
                f'Plano:    {plan_label(aceite.plan)}',
                f'Aceite:   {aceite.accepted_email} em '
                f'{timezone.localtime(aceite.created_at).strftime("%d/%m/%Y %H:%M")}',
                f'Contrato: versão {aceite.version}',
                '',
                'Console: /instalacao/contratos/',
            ]),
        )
    except Exception:                                   # noqa: BLE001
        # Sem registro de erro aqui: este é o aviso interno, e o aceite já
        # aparece no console de qualquer forma. O que não pode faltar é a
        # via do contratante, e essa tem `email_error`.
        return False
    return True
