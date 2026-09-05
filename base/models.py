import uuid

from django.db import models


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.BigIntegerField(default=1)

    class Meta:
        abstract = True


class TenantModel(TimestampedModel):
    tenant = models.ForeignKey('tenancy.Tenant', on_delete=models.PROTECT)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'id'],
                name='%(app_label)s_%(class)s_tenant_id_uniq',
            ),
        ]
