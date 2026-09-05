def scope_to_tenant(queryset, context):
    """Filter a tenant-scoped queryset by the current AccessContext.

    Returns an empty queryset whenever there is no resolved context, so a
    missing/invalid membership never falls back to returning every tenant's
    rows.
    """
    if context is None:
        return queryset.none()
    return queryset.filter(tenant_id=context.tenant_id)
