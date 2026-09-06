from django.db import models

from base.models import TenantModel


class Notification(TenantModel):
    user = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=60)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    sanitized_title = models.CharField(max_length=255)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'user', 'read_at'], name='notifications_user_unread_idx'),
        ]

    def __str__(self):
        return self.sanitized_title
