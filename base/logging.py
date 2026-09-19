import logging
import re

from django.views.debug import SafeExceptionReporterFilter

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


class NoPostDataExceptionReporterFilter(SafeExceptionReporterFilter):
    """Used for admin error e-mails (DEFAULT_EXCEPTION_REPORTER_FILTER).

    Django's own filter only redacts POST fields whose *name* looks
    sensitive (password, token, ...); it has no way to know that
    `chief_complaint` or `hpi` is clinical text. Rather than enumerate
    every clinical field name across every app, suppress POST data from
    error alerts entirely -- an alert needs the traceback and request
    path, never the request body.
    """

    #: Marcador no lugar do valor. O **nome** da variável fica: saber que
    #: existia um `encounter` naquele quadro ajuda a depurar, e o conteúdo
    #: dele não ajuda nada que valha o risco.
    PLACEHOLDER = '[SUPRIMIDO]'

    def get_post_parameters(self, request):
        return {}

    def get_traceback_frame_variables(self, request, tb_frame):
        """Nomes das variáveis locais, nunca os valores.

        Suprimir o corpo do POST e parar por aí resolvia metade do
        problema: o mesmo texto clínico reaparecia no relatório como
        variável local do quadro que estourou -- `form.cleaned_data`,
        `encounter`, `patient`, o `content` da mensagem do chat. A
        filtragem herdada do Django olha o nome da variável, e nenhum
        desses nomes parece sensível.

        Não há aqui o dilema que há no POST: um alerta de erro precisa do
        traceback, do caminho e do tipo da exceção. O conteúdo das
        variáveis é comodidade, e comodidade não justifica mandar
        prontuário por e-mail.
        """
        return [
            (nome, self.PLACEHOLDER)
            for nome, _valor in super().get_traceback_frame_variables(request, tb_frame)
        ]
