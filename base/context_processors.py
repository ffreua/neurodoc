"""Context shared by the Duralux application shell.

Everything here is derived from ``request.access_context`` and therefore
scoped to the tenant of the current request; nothing is cached across
requests. Outside ``/app/`` the processor returns the empty shell so
public pages (landing, authentication, document access) render without a
sidebar.
"""
from django.urls import Resolver404, resolve


def _section(request):
    match = getattr(request, 'resolver_match', None)
    if match is None:
        # Context processors run before the view for some error paths.
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return ''
    return match.namespace or ''


def _initials(user):
    parts = [p for p in (user.first_name, user.last_name) if p]
    if parts:
        return ''.join(p[0] for p in parts[:2]).upper()
    return (user.email or '?')[0].upper()


def shell(request):
    user = getattr(request, 'user', None)
    context = getattr(request, 'access_context', None)
    data = {
        'nd_section': _section(request),
        'nd_tenant': None,
        'nd_roles': [],
        'nd_unread_notifications': 0,
        'nd_recent_notifications': (),
        'nd_user_initials': _initials(user) if user is not None and user.is_authenticated else '',
    }
    if context is None:
        return data

    from notifications.models import Notification
    from tenancy.models import Tenant

    mine = Notification.objects.filter(tenant_id=context.tenant_id, user_id=context.user_id)
    data['nd_tenant'] = Tenant.objects.filter(id=context.tenant_id).first()
    data['nd_roles'] = sorted(context.permissions)
    data['nd_unread_notifications'] = mine.filter(read_at__isnull=True).count()
    data['nd_recent_notifications'] = list(mine.order_by('-created_at')[:5])
    return data
