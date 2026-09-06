class ProviderUnavailable(Exception):
    """AI disabled at the platform level, or the selected provider has no
    credential configured. Never a reason to fall back to another provider
    silently -- the caller must fail the job (or refuse to enqueue it).
    """
