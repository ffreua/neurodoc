import logging
import re

from django.views.debug import ExceptionReporter, SafeExceptionReporterFilter

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

    #: Valor com jeito de credencial embutida em URL --
    #: `esquema://usuario:senha@host`. Procurado no VALOR e nao no nome.
    #:
    #: O usuario e `*` e nao `+` de proposito: o Redis da casa conecta como
    #: `redis://:SENHA@redis:6379`, com usuario **vazio**. Com `+` o padrao
    #: nao casava, e a senha do Redis continuava saindo em claro no e-mail
    #: de erro enquanto a do RabbitMQ ja saia escondida.
    CREDENCIAL_EM_URL = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]*:[^/\s@]+@')

    def get_post_parameters(self, request):
        return {}

    def cleanse_setting(self, key, value):
        """Esconde tambem o segredo que esta no VALOR, nao no nome.

        A filtragem do Django decide pelo **nome** do setting: esconde o
        que casa com `API|TOKEN|KEY|SECRET|PASS|SIGNATURE`. Nomes como
        `CELERY_BROKER_URL`, `REDIS_BASE`, `AI_EVENTS_REDIS_URL`,
        `TEAMCHAT_REDIS_URL` e `CACHES` nao casam com nenhum deles -- e sao
        exatamente os que carregam a senha embutida na URL de conexao
        (`amqp://neurodoc:SENHA@rabbitmq:5672/...`).

        O resultado, medido antes desta correcao: o corpo do e-mail de erro
        que o `AdminEmailHandler` manda para `ALERT_ADMIN_EMAILS` despejava
        os 206 settings e trazia as senhas do Redis e do RabbitMQ em texto
        claro, por SMTP, a cada 500 nao tratado. O `RedactSensitiveDataFilter`
        acima nao alcanca isso: ele age sobre a mensagem do registro de log,
        e o corpo do e-mail e montado a parte, pelo `ExceptionReporter`.

        Decidir pelo valor, e nao pelo nome, e o que fecha a classe inteira
        de defeito em vez de um caso: um setting novo com credencial dentro
        ja nasce escondido, sem ninguem precisar lembrar de acrescentar o
        nome a uma lista.
        """
        if isinstance(value, str) and self.CREDENCIAL_EM_URL.match(value):
            return self.cleansed_substitute
        return super().cleanse_setting(key, value)

    def get_safe_request_meta(self, request):
        """`QUERY_STRING` tambem carrega o termo de busca.

        Tirar a query string da `Request URL` e da secao `GET` nao bastava:
        o mesmo texto reaparecia na secao META, em `QUERY_STRING`, inteiro.
        E o mesmo defeito que ja havia entre o corpo do POST e as variaveis
        locais -- o dado suprimido num lugar volta por outro --, e a licao
        e a mesma: procurar o VALOR no relatorio pronto, e nao confiar em
        ter tapado todas as saidas.
        """
        meta = super().get_safe_request_meta(request)
        if meta.get('QUERY_STRING'):
            meta['QUERY_STRING'] = self.PLACEHOLDER
        return meta

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


class NoQueryStringExceptionReporter(ExceptionReporter):
    """Tira a query string do relatorio de erro: nome e valor.

    O corpo do e-mail que o `AdminEmailHandler` manda traz `Request URL:`
    com a URL inteira e uma secao `GET` com cada par. A busca de paciente e
    por query string (`/app/patients/?q=Carlos`), e o mesmo vale para a
    busca global e para a busca rapida da agenda: o nome do paciente ia por
    SMTP para a caixa de quem opera o servidor, a cada 500 nao tratado.

    E a mesma regra que `NoPostDataExceptionReporterFilter` ja aplica ao
    corpo do POST e as variaveis locais, e pela mesma razao. O caminho
    (`request.path_info`) fica, porque e ele que diz qual tela estourou, e
    nao carrega dado de paciente -- os identificadores nas rotas de `/app/`
    sao UUID.

    Precisa ser um **reporter**, e nao o filtro: `get_traceback_data` e
    metodo de `ExceptionReporter`. Escrito no filtro, o mesmo codigo vira
    metodo que ninguem chama -- foi o que aconteceu na primeira tentativa,
    e so a medicao do corpo do e-mail denunciou.
    """

    #: O mesmo marcador do filtro, pela mesma razao: o nome do parametro
    #: ajuda a depurar, o valor nao vale o risco.
    PLACEHOLDER = NoPostDataExceptionReporterFilter.PLACEHOLDER

    def get_traceback_data(self):
        dados = super().get_traceback_data()
        if 'request_GET_items' in dados:
            dados['request_GET_items'] = [
                (nome, self.PLACEHOLDER) for nome, _valor in dados['request_GET_items']
            ]
        uri = dados.get('request_insecure_uri')
        if isinstance(uri, str) and '?' in uri:
            dados['request_insecure_uri'] = f'{uri.split("?", 1)[0]}?{self.PLACEHOLDER}'
        return dados
