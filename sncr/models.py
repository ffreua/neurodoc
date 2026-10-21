"""Numeração do SNCR: a configuração, os pedidos, os blocos e cada número.

O SNCR (Sistema Nacional de Controle de Receituários, Anvisa) entrega ao
médico **blocos** de números para a Receita de Controle Especial (RCE) e a
Receita Sujeita à Retenção (RET); quem controla qual número já foi usado
é a plataforma (FAQ Integração P38). Este app guarda isso. Desenho e
decisões em `docs/sncr/DECISOES.md`.

**O bloco é do médico, não da clínica.** A numeração é atrelada ao CPF do
prescritor (FAQ P31): o médico que atende em duas clínicas tem um bloco
só, usado nas duas. Por isso os modelos ligam ao `PhysicianProfile`
(global) e não herdam `TenantModel`; a clínica fica registrada só onde o
número foi **usado**.

**Nada se apaga.** Bloco recebido e número entregue são fatos externos —
existem na Anvisa independentemente do NeuroDoc. Apagar uma linha daqui
não devolve nada lá (não há cancelamento, FAQ P35–36) e faria o mesmo
número voltar a parecer livre. As chaves estrangeiras são `PROTECT`.
"""

from django.conf import settings
from django.db import models

from base.models import TimestampedModel


class Ambiente(models.TextChoices):
    HOMOLOGACAO = 'homologacao', 'Homologação (treinamento)'
    PRODUCAO = 'producao', 'Produção'


#: Endereços do Manual da API SNCR v5, §2.1. Em código e não em
#: configuração livre: um campo de texto deixaria apontar a numeração de
#: produção para qualquer servidor, e a escolha que existe é só entre os dois.
BASES = {
    Ambiente.HOMOLOGACAO: 'https://api-gateway.hmg.apps.anvisa.gov.br/api-sncr/api/v1/',
    Ambiente.PRODUCAO: 'https://api-gateway.prd.apps.anvisa.gov.br/api-sncr/api/v1/',
}


class TipoReceita(models.TextChoices):
    RCE = 'RCE', 'Receita de Controle Especial'
    RET = 'RET', 'Receita Sujeita à Retenção'


class Configuracao(TimestampedModel):
    """A configuração do SNCR da instalação — uma linha só.

    **Nasce desligada** e sem CNPJ: a integração só funciona depois de
    alguém, de propósito, informar o CNPJ da mantenedora
    (`docs/sncr/PENDENCIA-CNPJ.md`) e ligar. Nunca o CNPJ de uma clínica
    cliente (FAQ Integração P34).
    """

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    ativo = models.BooleanField('integração ligada', default=False)
    ambiente = models.CharField('ambiente', max_length=20, choices=Ambiente.choices, default=Ambiente.HOMOLOGACAO)
    cnpj_mantenedora = models.CharField('CNPJ da mantenedora', max_length=14, blank=True)

    class Meta:
        verbose_name = 'configuração do SNCR'
        verbose_name_plural = 'configuração do SNCR'

    @classmethod
    def carregar(cls):
        return cls.objects.get_or_create(singleton=True)[0]

    @property
    def base_url(self):
        return BASES[self.ambiente]


class EstadoPedido(models.TextChoices):
    AGUARDANDO_LOGIN = 'aguardando_login', 'Aguardando o login no Gov.br'
    ENVIANDO = 'enviando', 'Enviando à Anvisa'
    CONCLUIDO = 'concluido', 'Bloco recebido'
    RECUSADO = 'recusado', 'Recusado pela Anvisa'
    FALHOU = 'falhou', 'Não enviado'
    INCERTO = 'incerto', 'Resultado incerto'
    EXPIRADO = 'expirado', 'Login não concluído'


class PedidoNumeracao(TimestampedModel):
    """Um pedido de bloco, do clique do médico à resposta da Anvisa.

    `INCERTO` é o estado que importa: a resposta se perdeu **depois** de o
    pedido sair, e a Anvisa pode ter entregado o bloco. Ele não é repetido
    sozinho (decisão I6) e barra um pedido novo até alguém conciliar —
    repetir às cegas pode gastar mais um dos três pedidos do mês.
    """

    medico = models.ForeignKey('accounts.PhysicianProfile', on_delete=models.PROTECT, related_name='pedidos_sncr')
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    tenant = models.ForeignKey('tenancy.Tenant', on_delete=models.PROTECT, related_name='+')
    tipo = models.CharField(max_length=3, choices=TipoReceita.choices)
    ambiente = models.CharField(max_length=20, choices=Ambiente.choices)
    conselho = models.CharField(max_length=8, default='CRM')
    uf = models.CharField(max_length=2)
    documento = models.CharField('número no conselho', max_length=20)
    cnpj = models.CharField(max_length=14)
    estado = models.CharField(max_length=20, choices=EstadoPedido.choices, default=EstadoPedido.AGUARDANDO_LOGIN)
    mensagem = models.CharField('mensagem ao médico', max_length=500, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'pedido de numeração SNCR'
        verbose_name_plural = 'pedidos de numeração SNCR'
        indexes = [models.Index(fields=['medico', 'tipo', 'ambiente', 'estado'], name='sncr_pedido_medico_idx')]


class BlocoNumeracao(TimestampedModel):
    """O bloco que a Anvisa entregou, com início e fim como vieram.

    `utilizavel` é falso quando início e fim não formam uma faixa que se
    saiba enumerar (decisão I8): o bloco fica registrado, e nenhum número
    é inventado.
    """

    pedido = models.OneToOneField(PedidoNumeracao, on_delete=models.PROTECT, related_name='bloco')
    medico = models.ForeignKey('accounts.PhysicianProfile', on_delete=models.PROTECT, related_name='blocos_sncr')
    tipo = models.CharField(max_length=3, choices=TipoReceita.choices)
    ambiente = models.CharField(max_length=20, choices=Ambiente.choices)
    inicio = models.CharField(max_length=64)
    fim = models.CharField(max_length=64)
    quantidade = models.PositiveIntegerField(null=True, blank=True)
    utilizavel = models.BooleanField(default=True)
    motivo_bloqueio = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'bloco de numeração SNCR'
        verbose_name_plural = 'blocos de numeração SNCR'


class EstadoNumero(models.TextChoices):
    LIVRE = 'livre', 'Livre'
    RESERVADO = 'reservado', 'Reservado para uma receita'
    CONSUMIDO = 'consumido', 'Usado numa receita emitida'
    PERDIDO = 'perdido', 'Perdido'


class NumeroSncr(TimestampedModel):
    """Um número do bloco, como texto íntegro.

    Texto e não inteiro: zeros à esquerda, prefixos e o comprimento são do
    número (a Anvisa anunciou a ampliação do formato). `UNIQUE` por
    ambiente, tipo e número é o que impede o mesmo número em duas receitas
    mesmo que dois blocos se sobreponham (decisão I7).
    """

    bloco = models.ForeignKey(BlocoNumeracao, on_delete=models.PROTECT, related_name='numeros')
    medico = models.ForeignKey('accounts.PhysicianProfile', on_delete=models.PROTECT, related_name='+')
    tipo = models.CharField(max_length=3, choices=TipoReceita.choices)
    ambiente = models.CharField(max_length=20, choices=Ambiente.choices)
    numero = models.CharField(max_length=64)
    ordem = models.PositiveIntegerField()
    estado = models.CharField(max_length=12, choices=EstadoNumero.choices, default=EstadoNumero.LIVRE)
    documento = models.ForeignKey(
        'documents.MedicalDocument', on_delete=models.SET_NULL, null=True, blank=True, related_name='numeros_sncr',
    )
    tenant = models.ForeignKey('tenancy.Tenant', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    reservado_em = models.DateTimeField(null=True, blank=True)
    consumido_em = models.DateTimeField(null=True, blank=True)
    motivo_perda = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'número SNCR'
        verbose_name_plural = 'números SNCR'
        constraints = [
            models.UniqueConstraint(fields=['ambiente', 'tipo', 'numero'], name='sncr_numero_unico'),
        ]
        indexes = [
            models.Index(fields=['medico', 'tipo', 'ambiente', 'estado', 'ordem'], name='sncr_numero_livre_idx'),
        ]

    def __str__(self):
        return f'{self.tipo} {self.numero}'
