from tenancy.models import Membership, MembershipStatus

from .models import Notification


def notify_role(tenant, roles, kind, sanitized_title, target_type='', target_id=None):
    memberships = Membership.objects.filter(
        tenant=tenant, status=MembershipStatus.ACTIVE, roles__overlap=list(roles),
    )
    notifications = [
        Notification(
            tenant=tenant, user_id=m.user_id, kind=kind, sanitized_title=sanitized_title,
            target_type=target_type, target_id=target_id,
        )
        for m in memberships
    ]
    return Notification.objects.bulk_create(notifications)


def notify_user(tenant, user_id, kind, sanitized_title, target_type='', target_id=None):
    return Notification.objects.create(
        tenant=tenant, user_id=user_id, kind=kind, sanitized_title=sanitized_title,
        target_type=target_type, target_id=target_id,
    )


def mark_read(notification):
    from django.utils import timezone

    notification.read_at = timezone.now()
    notification.save(update_fields=['read_at'])
    return notification
