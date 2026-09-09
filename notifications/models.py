from django.db import models

from base.models import TenantModel


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
