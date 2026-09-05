from .models import AuditEvent, AuditOutcome


def protect_ip(ip):
    """Mask the host part of an IP address before it is stored."""
    if not ip:
        return ''
    if ':' in ip:
        parts = ip.split(':')
        return ':'.join(parts[:4]) + '::'
    parts = ip.split('.')
    if len(parts) == 4:
        parts[-1] = '0'
        return '.'.join(parts)
    return ''


def record_audit_event(
    actor, tenant, action, *, object_type='', object_id=None,
    purpose='', outcome=AuditOutcome.SUCCESS, request_id=None,
    origin_ip=None, integrity_metadata=None,
):
    """Single explicit entry point for writing AuditEvent rows.

    Callers must never pass clinical text, tokens, or secrets in `purpose`
    or `integrity_metadata`.
    """
    return AuditEvent.objects.create(
        actor=actor,
        tenant=tenant,
        action=action,
        object_type=object_type,
        object_id=object_id,
        purpose=(purpose or '')[:255],
        outcome=outcome,
        request_id=request_id,
        origin_ip_protected=protect_ip(origin_ip),
        integrity_metadata=integrity_metadata or {},
    )
