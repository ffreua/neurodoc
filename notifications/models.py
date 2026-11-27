from django.db import models

from base.models import TenantModel, TimestampedModel


class Notification(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=60)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    sanitized_title = models.CharField(max_length=255)
    #: Fatos de identificação capturados na criação, para a tela dizer de
    #: **quem** se trata sem uma consulta por linha.
    #:
    #: Guarda nome e número de prontuário do paciente, e o rótulo do
    #: assunto ("Receita de controle especial"). Nunca conteúdo clínico —
    #: é o mesmo limite de `sanitized_title`, e pela mesma razão: esta
    #: linha é lida em toda requisição para montar o sino do cabeçalho.
    #:
    #: Retrato, e não referência viva: um documento descartado ou um
    #: pedido já atendido continuam legíveis na caixa de quem os recebeu.
    #: O nome pode envelhecer se o cadastro for corrigido; para uma caixa
    #: de avisos, é troca melhor do que uma consulta por notificação.
    context = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'user', 'read_at'], name='notifications_user_unread_idx'),
        ]

    def __str__(self):
        return self.sanitized_title

class PushSubscription(models.Model):
    """Um aparelho que recebe os avisos de uma pessoa (`notifications.push`).

    **Da pessoa, e não da clínica** — por isso não é `TenantModel`. O
    aparelho é um só e a pessoa que trabalha em duas clínicas quer o aviso
    das duas nele; uma inscrição por clínica pediria ao navegador duas
    inscrições no mesmo endereço, que ele não tem como dar. O que o aviso
    diz não carrega nada da clínica (só o tipo), e quem o abre cai no login
    e no seletor de organização de sempre.

    `endpoint` é a credencial de entrega: quem o tem consegue mandar aviso
    para aquele aparelho (com a chave VAPID). Não vai para log nem para a
    trilha, e a tela mostra só o rótulo do aparelho.
    """

    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE,
                             related_name='push_subscriptions')
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=120)
    auth = models.CharField(max_length=40)
    #: "iPhone · Safari": o bastante para a pessoa reconhecer o aparelho.
    aparelho = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ultimo_envio_em = models.DateTimeField(null=True, blank=True)
    falhas = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = 'aparelho com avisos'
        verbose_name_plural = 'aparelhos com avisos'

    def __str__(self):
        return self.aparelho or 'Aparelho'


class Comunicado(TimestampedModel):
    """Um comunicado da instalação, escrito no console (`notifications.comunicados`).

    **Da instalação, e não de uma clínica** — quem escreve é quem opera o
    servidor, e o mesmo texto vai a várias clínicas. Cada destinatário
    recebe uma linha no sino da clínica dele (`Notification`, tipo
    `comunicado`) e, se ligou os avisos, o aviso no celular.

    O texto é **da casa**, nunca de paciente: o console não tem acesso a
    prontuário, e o campo é para avisar manutenção, versão nova ou oferta.
    """

    class Categoria(models.TextChoices):
        AVISO = 'aviso', 'Aviso do sistema'
        PROPAGANDA = 'propaganda', 'Propaganda'

    class Publico(models.TextChoices):
        TODOS = 'todos', 'Todas as clínicas'
        PLANO = 'plano', 'As clínicas de um plano'
        CLINICA = 'clinica', 'Uma clínica'
        PAPEL = 'papel', 'Um papel, em todas as clínicas'

    class Situacao(models.TextChoices):
        NA_FILA = 'fila', 'Na fila'
        ENVIANDO = 'enviando', 'Enviando'
        ENVIADO = 'enviado', 'Enviado'
        FALHOU = 'falhou', 'Falhou'

    categoria = models.CharField(max_length=20, choices=Categoria.choices)
    titulo = models.CharField(max_length=60)
    texto = models.TextField()
    #: Caminho do próprio site (`/ajuda/...`), opcional. Endereço de fora
    #: não entra: o comunicado chega com a cara do produto, e um link para
    #: outro domínio ali é o formato exato de uma fraude.
    link = models.CharField(max_length=200, blank=True)
    publico = models.CharField(max_length=20, choices=Publico.choices)
    #: O código do plano, o id da clínica ou o papel, conforme `publico`.
    filtro = models.CharField(max_length=64, blank=True)
    criado_por = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True,
                                   related_name='+')
    situacao = models.CharField(max_length=20, choices=Situacao.choices, default=Situacao.NA_FILA)
    enviado_em = models.DateTimeField(null=True, blank=True)
    pessoas = models.PositiveIntegerField(default=0)
    aparelhos_entregues = models.PositiveIntegerField(default=0)
    aparelhos_falhas = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'comunicado'
        verbose_name_plural = 'comunicados'
        ordering = ['-created_at']

    def __str__(self):
        return self.titulo
