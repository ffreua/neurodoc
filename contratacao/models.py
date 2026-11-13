"""O que a contratação pela página de vendas guarda.

**O pedido é da instalação, e não de uma clínica.** Quem paga ainda não tem
clínica: ela nasce depois, pelo convite que o pagamento emite
(`tenancy.invitations`), pelo mesmo cadastro e pelo mesmo aceite do contrato
de quem recebe o código à mão. Por isso nada aqui herda de `TenantModel`.

**O aviso da Asaas é gravado antes de ser entendido.** `EventoAsaas` guarda o
corpo inteiro com o `id` do evento como chave única: a Asaas entrega "pelo
menos uma vez", e a mesma confirmação chegando duas vezes não pode emitir dois
convites. Gravar e responder 200 é o que a porta faz; entender é do worker.
"""

from django.db import models

from base.models import TimestampedModel


class Configuracao(TimestampedModel):
    """A chave do checkout na instalação — uma linha só, e nasce desligada.

    Desligada, a vitrine volta ao "Quero este plano" do formulário de contato
    e `/contratar/` devolve aos planos. **Os avisos da Asaas continuam sendo
    recebidos** com ela desligada: desligar é parar de vender, não deixar de
    saber de um pagamento que já estava em curso.
    """

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    ativo = models.BooleanField('checkout ligado', default=False)

    class Meta:
        verbose_name = 'configuração da contratação'
        verbose_name_plural = 'configuração da contratação'

    @classmethod
    def carregar(cls):
        return cls.objects.get_or_create(singleton=True)[0]


class StatusPedido(models.TextChoices):
    PREPARANDO = 'preparando', 'Preparando o pagamento'
    AGUARDANDO = 'aguardando', 'Aguardando pagamento'
    PAGO = 'pago', 'Pago'
    CANCELADO = 'cancelado', 'Cancelado'
    EXPIRADO = 'expirado', 'Expirado'
    FALHOU = 'falhou', 'Não abriu'


class Pedido(TimestampedModel):
    """Uma tentativa de contratar um plano pago pela página de vendas.

    O preço é **gravado** no pedido, e não relido do catálogo: é o que foi
    oferecido a quem clicou, e o aviso de pagamento é conferido contra ele.
    Se o preço do catálogo mudar entre o clique e o pagamento, vale o do
    pedido — o mesmo princípio do aceite, que prevalece sobre a vitrine.
    """

    #: O `id` (UUID4, 122 bits sorteados) é também o endereço da página do
    #: pedido e o retorno que a Asaas recebe. A página só diz o estado; o botão
    #: de criar a clínica aparece **só** no navegador que fez o pedido (sessão),
    #: e o link vai ao e-mail informado. Um token à parte não protegeria mais.
    status = models.CharField(max_length=12, choices=StatusPedido.choices,
                              default=StatusPedido.PREPARANDO, db_index=True)

    plano = models.CharField(max_length=16)
    periodicidade = models.CharField(max_length=12)
    #: Valor de cada cobrança e o total de 12 meses, em centavos.
    valor_pagamento_centavos = models.PositiveIntegerField()
    valor_ano_centavos = models.PositiveIntegerField()
    #: Quantas cobranças cabem nos 12 meses: 1, 2 ou 4.
    cobrancas_previstas = models.PositiveSmallIntegerField(default=1)

    nome = models.CharField(max_length=150)
    email = models.EmailField(max_length=254)
    #: A versão do contrato que estava publicada quando a pessoa declarou tê-lo
    #: lido. O aceite formal continua sendo o do cadastro da clínica.
    contrato_versao = models.CharField(max_length=16)
    origem_ip = models.GenericIPAddressField(null=True, blank=True)

    checkout_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    checkout_link = models.URLField(max_length=500, blank=True)
    assinatura_id = models.CharField(max_length=64, blank=True, db_index=True)
    cliente_asaas_id = models.CharField(max_length=64, blank=True)
    falha = models.TextField(blank=True)

    pago_em = models.DateTimeField(null=True, blank=True)
    convite = models.OneToOneField('tenancy.Invitation', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='pedido_asaas')
    #: O código do convite, cifrado (`base.crypto`), para a página do pedido
    #: poder mostrar o botão de criar a clínica a quem pagou — o convite em si
    #: só guarda o hash, e o token em claro não poderia ser recuperado.
    convite_token_cifrado = models.TextField(blank=True)
    convite_token_meta = models.JSONField(default=dict, blank=True)
    email_enviado_em = models.DateTimeField(null=True, blank=True)

    @property
    def valor_pagamento_brl(self):
        from tenancy.plans import brl

        return brl(self.valor_pagamento_centavos)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'pedido de contratação'
        verbose_name_plural = 'pedidos de contratação'


class Cobranca(models.Model):
    """Cada cobrança que a Asaas gerou para um pedido, no estado mais recente.

    Um pedido anual tem uma; o semestral, duas; o trimestral, quatro — as que
    vêm depois da primeira são as que podem atrasar, e é para elas que esta
    tabela existe. Uma linha por `payment.id` da Asaas.
    """

    pedido = models.ForeignKey(Pedido, null=True, blank=True, on_delete=models.PROTECT,
                               related_name='cobrancas')
    payment_id = models.CharField(max_length=64, unique=True)
    assinatura_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=40, blank=True)
    forma = models.CharField(max_length=20, blank=True)
    valor = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vencimento = models.DateField(null=True, blank=True)
    ultimo_evento = models.CharField(max_length=60, blank=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['vencimento', 'payment_id']


class EventoAsaas(models.Model):
    """Um aviso recebido da Asaas, guardado antes de qualquer interpretação."""

    event_id = models.CharField(max_length=120, unique=True)
    tipo = models.CharField(max_length=60, db_index=True)
    payload = models.JSONField()
    recebido_em = models.DateTimeField(auto_now_add=True, db_index=True)
    processado_em = models.DateTimeField(null=True, blank=True, db_index=True)
    tentativas = models.PositiveSmallIntegerField(default=0)
    erro = models.TextField(blank=True)

    class Meta:
        ordering = ['-recebido_em']
