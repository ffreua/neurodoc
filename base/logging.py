import logging
import re

SENSITIVE_KEYS = ('password', 'token', 'secret', 'otp', 'authorization', 'pfx', 'code_hash')
_PATTERN = re.compile(
    r'(?i)(' + '|'.join(SENSITIVE_KEYS) + r')(["\']?\s*[:=]\s*["\']?)([^\s,;&"\']+)',
)


def _redact(value):
    if isinstance(value, str):
        return _PATTERN.sub(r'\1\2[REDACTED]', value)
    return value


class RedactSensitiveDataFilter(logging.Filter):
    """Strips password/token/secret-like values out of log records."""

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: _redact(value) for key, value in record.args.items()}
            else:
                record.args = tuple(_redact(arg) for arg in record.args)
        return True
