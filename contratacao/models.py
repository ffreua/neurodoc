"""O que a contratação pela página de vendas guarda.

**O pedido é da instalação, e não de uma clínica.** Quem paga ainda não tem
clínica: ela nasce depois, pelo convite que o pagamento emite
(`tenancy.invitations`), pelo mesmo cadastro e pelo mesmo aceite do contrato
de quem recebe o código à mão. Por isso o pedido não herda de `TenantModel`.
A exceção é a renovação (1.47): quem renova já tem clínica, e o pedido aponta
para ela (`Pedido.tenant`). E a `Vigencia` é da clínica — o período pago que
ela tem —, e essa sim é `TenantModel`.

**O aviso da Asaas é gravado antes de ser entendido.** `EventoAsaas` guarda o
corpo inteiro com o `id` do evento como chave única: a Asaas entrega "pelo
menos uma vez", e a mesma confirmação chegando duas vezes não pode emitir dois
convites. Gravar e responder 200 é o que a porta faz; entender é do worker.
"""

from django.db import models

from base.models import TenantModel, TimestampedModel


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
    #: O valor do pagamento único do período e o equivalente em 12 meses
    #: (só para comparar as formas), em centavos.
    valor_pagamento_centavos = models.PositiveIntegerField()
    valor_ano_centavos = models.PositiveIntegerField()
    #: Quantas cobranças o pedido gera. Desde a 1.47 sempre 1: cada período é
    #: pago de uma vez. Os pedidos da 1.46 (assinatura de 2 ou 4) nunca foram
    #: abertos em produção — o checkout nasceu desligado —, e a coluna fica.
    cobrancas_previstas = models.PositiveSmallIntegerField(default=1)
    #: A clínica que renova (1.47). Vazio no pedido da página de vendas, em
    #: que a clínica ainda não existe: ali o pagamento emite convite; aqui ele
    #: abre o período seguinte (`Vigencia`).
    tenant = models.ForeignKey('tenancy.Tenant', null=True, blank=True, on_delete=models.PROTECT,
                               related_name='pedidos_de_renovacao')
    #: Quem clicou em Renovar.
    solicitado_por = models.ForeignKey('accounts.User', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')

    nome = models.CharField(max_length=150)
    email = models.EmailField(max_length=254)
    #: A versão do contrato que estava publicada quando a pessoa declarou tê-lo
    #: lido. O aceite formal continua sendo o do cadastro da clínica.
    contrato_versao = models.CharField(max_length=16)
    origem_ip = models.GenericIPAddressField(null=True, blank=True)
    #: O aceite da renovação (contrato 2.2, cláusula 3.2): a renovação pede
    #: "li e aceito" de novo, e a prova fica aqui, no ato de quem clicou —
    #: e não num segundo `ContractAcceptance`, que é um por clínica e por
    #: versão (a clínica que renova duas vezes na 2.2 aceitaria a mesma
    #: versão duas vezes). O texto inteiro, como no aceite do cadastro
    #: (cláusula 2.2). Vazio no pedido da página de vendas, cujo aceite formal
    #: é o do cadastro da clínica.
    aceite_em = models.DateTimeField(null=True, blank=True)
    aceite_sha256 = models.CharField(max_length=64, blank=True)
    aceite_texto = models.TextField(blank=True)
    aceite_user_agent = models.CharField(max_length=255, blank=True)
    poderes_declarados = models.BooleanField(default=False)

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

    @property
    def e_renovacao(self):
        return self.tenant_id is not None

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'pedido de contratação'
        verbose_name_plural = 'pedidos de contratação'


class OrigemVigencia(models.TextChoices):
    ACEITE = 'aceite', 'Contratação (aceite do contrato)'
    RENOVACAO = 'renovacao', 'Renovação paga pelo sistema'
    CONSOLE = 'console', 'Registrada no console'


class Vigencia(TenantModel):
    """Um período pago de um plano: de quando a quando, quanto e de onde veio.

    **Por que uma tabela, e não uma data no `Tenant`.** Desde a 1.47 (contrato
    2.2) o período é o que se paga — três, seis ou doze meses —, e a clínica
    renova quantas vezes quiser. Uma data só seria sobrescrita a cada
    renovação, e a pergunta "o que esta clínica pagou, e quando?" deixaria de
    ter resposta. Aqui cada período é uma linha que não muda depois de gravada,
    menos os dois carimbos de aviso.

    **A vigência não diz o que a clínica pode.** Quem decide é `Tenant.plan`,
    como sempre; isto é o registro do que foi pago e a base dos avisos. Ela só
    **muda** o plano uma vez, e por contrato: quinze dias depois do fim sem
    renovação, a clínica passa ao Gratuito (cláusula 3.4 da 2.2,
    `vigencias.rebaixar`), e a renovação paga depois a devolve.

    **Só existe para quem tem período.** O Gratuito não vence, o Personalizado
    é combinado, e as clínicas anteriores à 1.47 não ganham vigência por
    migração: entre elas há cortesia e condição combinada, e um aviso de
    "renove" na tela de quem não paga seria pior que nenhum. O console as
    registra uma a uma (`origem=console`).
    """

    plano = models.CharField(max_length=16)
    periodicidade = models.CharField(
        max_length=12,
        choices=[('anual', 'Anual'), ('semestral', 'Semestral'), ('trimestral', 'Trimestral')],
    )
    #: Início e fim do período. O fim é o instante em que deixa de valer —
    #: a meia-noite de Brasília do dia seguinte ao último dia, como o
    #: vencimento do aceite.
    inicio = models.DateTimeField()
    fim = models.DateTimeField(db_index=True)
    #: O que foi pago pelo período, em centavos. Nulo quando foi combinado à
    #: parte e registrado no console sem valor.
    valor_centavos = models.PositiveIntegerField(null=True, blank=True)
    origem = models.CharField(max_length=12, choices=OrigemVigencia.choices)
    #: Um pedido pago abre **um** período, pela restrição do banco: o mesmo
    #: aviso de pagamento chegando duas vezes não dá dois períodos.
    pedido = models.OneToOneField(Pedido, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name='vigencia')
    #: `SET_NULL`, e não `PROTECT`: o período guarda as próprias datas e o
    #: valor, e o aceite é só de onde ele veio — prender o aceite aqui
    #: impediria a limpeza dos roteiros, que aposentam clínicas apagando-o.
    aceite = models.OneToOneField('tenancy.ContractAcceptance', null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='vigencia')
    registrado_por = models.ForeignKey('accounts.User', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+')
    nota = models.CharField(max_length=255, blank=True)
    #: Os avisos por e-mail, uma vez cada (`vigencias.avisar`): trinta e
    #: quinze dias antes do fim (contrato 2.2, cláusula 3.2) e no fim.
    aviso_30_em = models.DateTimeField(null=True, blank=True)
    aviso_15_em = models.DateTimeField(null=True, blank=True)
    aviso_vencido_em = models.DateTimeField(null=True, blank=True)
    #: Quando a clínica passou ao Gratuito por não renovar (cláusula 3.4), e
    #: os vínculos que perderam o papel médico nisso — devolvidos pela
    #: renovação paga depois, como a conversão da degustação.
    rebaixada_em = models.DateTimeField(null=True, blank=True)
    medicos_retirados = models.JSONField(default=list, blank=True)

    @property
    def ultimo_dia(self):
        from .vigencias import ultimo_dia

        return ultimo_dia(self.fim)

    @property
    def valor_brl(self):
        from tenancy.plans import brl

        return brl(self.valor_centavos)

    class Meta(TenantModel.Meta):
        ordering = ['-fim']
        constraints = TenantModel.Meta.constraints + [
            models.CheckConstraint(condition=models.Q(fim__gt=models.F('inicio')),
                                   name='contratacao_vigencia_fim_depois_do_inicio'),
        ]
        verbose_name = 'vigência'
        verbose_name_plural = 'vigências'


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
