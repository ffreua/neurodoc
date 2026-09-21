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

#: Vigência do período contratado, em meses. O contrato é anual e vence na
#: data de aniversário do aceite (cláusula 2.2).
VIGENCIA_MESES = 12


def sha_do_texto():
    """SHA-256 do contrato como ele está agora.

    É o que transforma "versão 2026-09-20" em prova: a versão é um rótulo
    que alguém pode esquecer de trocar, o hash não.
    """
    return hashlib.sha256(contract.texto_simples().encode('utf-8')).hexdigest()


def _somar_um_ano(momento):
    """Mesma data, ano seguinte. Cuidando do 29 de fevereiro.

    `timedelta(days=365)` erraria por um dia toda vez que houvesse 29 de
    fevereiro no meio, e o vencimento de um contrato anual não pode andar
    sozinho. Quem assina em 29/02 vence em 28/02 — a regra do Código Civil
    para prazos que caem em data inexistente.
    """
    try:
        return momento.replace(year=momento.year + 1)
    except ValueError:
        return momento.replace(year=momento.year + 1, month=2, day=28)


def registrar_aceite(tenant, user, plan, ip=None, user_agent='', versao=None, quando=None):
    """Grava o aceite. Chamado de dentro da transação que cria a clínica."""
    agora = quando or timezone.now()
    return ContractAcceptance.objects.create(
        tenant=tenant,
        version=versao or contract.VERSAO,
        text_sha256=sha_do_texto(),
        plan=plan,
        accepted_by=user,
        # Nome montado do primeiro e do ultimo, e nao de `get_full_name()`:
        # aquele devolve o e-mail quando nao ha nome, e o aceite passaria a
        # dizer que "Fulano <fulano@...>" se chama "fulano@...".
        accepted_name=f'{user.first_name} {user.last_name}'.strip()[:255],
        accepted_email=user.email,
        source_ip=ip,
        user_agent=(user_agent or '')[:255],
        withdrawal_deadline=agora + timezone.timedelta(days=PRAZO_ARREPENDIMENTO_DIAS),
        expires_at=_somar_um_ano(agora),
    )


def _corpo(aceite):
    """A cópia que o contratante recebe.

    Começa pelos dados do aceite e só depois vem o contrato: quem abre
    este e-mail seis meses depois está procurando uma data ou um prazo, e
    não relendo catorze cláusulas para encontrá-la.

    O texto sai de `contract.texto_simples()`, o mesmo que a tela
    renderiza. Um segundo texto escrito à mão para o e-mail divergiria do
    primeiro exatamente onde não pode.
    """
    from .plans import plan_label

    cabecalho = [
        'Este e-mail é a sua via do contrato de adesão ao NeuroDoc.',
        'Guarde-o: ele registra o que foi aceito, por quem e quando.',
        '',
        f'Clínica:            {aceite.tenant.trade_name or aceite.tenant.legal_name}',
        f'CNPJ:               {aceite.tenant.cnpj}',
        f'Plano contratado:   {plan_label(aceite.plan)}',
        # Sem o nome entre parenteses quando ele nao existe: a conta recem
        # criada ainda nao tem nome, e a linha saia com o mesmo e-mail duas
        # vezes.
        f'Aceito por:         {aceite.accepted_name} <{aceite.accepted_email}>'
        if aceite.accepted_name else f'Aceito por:         {aceite.accepted_email}',
        f'Data e hora:        {timezone.localtime(aceite.created_at).strftime("%d/%m/%Y às %H:%M")}',
        f'Origem (IP):        {aceite.source_ip or "não registrado"}',
        f'Versão do contrato: {aceite.version}',
        f'Conferência:        SHA-256 {aceite.text_sha256}',
        '',
        f'Arrependimento até: {timezone.localtime(aceite.withdrawal_deadline).strftime("%d/%m/%Y")}'
        f' ({PRAZO_ARREPENDIMENTO_DIAS} dias corridos, cláusula 9)',
        f'Vencimento:         {timezone.localtime(aceite.expires_at).strftime("%d/%m/%Y")}',
        '',
        '-' * 70,
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
                f'Clínica:  {aceite.tenant.legal_name} (CNPJ {aceite.tenant.cnpj})',
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
