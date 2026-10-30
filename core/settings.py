import os
import re
from pathlib import Path
from urllib.parse import quote

import environ
from celery.schedules import crontab

from ops.env import read_env, secret


BASE_DIR = Path(__file__).resolve().parent.parent
if (BASE_DIR / '.env').exists():
    for key, value in read_env(BASE_DIR / '.env').items():
        os.environ.setdefault(key, value)
env = environ.Env()
DEBUG = env.bool('DEBUG', default=False)
SECRET_KEY = secret('DJANGO_SECRET_KEY')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

#: Redes de onde `X-Forwarded-For` pode ser acreditado (`base/net.py`).
#:
#: O padrao sao as faixas privadas, que e onde o Traefik roda: em
#: producao o app nao publica porta nenhuma e so e alcancavel por ele, de
#: modo que quem fala com o app ja esta dentro da rede do Swarm. Uma
#: faixa publica aqui -- as da Cloudflare, por exemplo -- so entra quando
#: aquele proxy for realmente o caminho de entrada, porque declarar
#: confiavel quem nao e devolve ao visitante o poder de escrever o
#: proprio IP no cabecalho.
TRUSTED_PROXIES = env.list('TRUSTED_PROXIES', default=[
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '::1/128',
])
PUBLIC_BASE_URL = env('PUBLIC_BASE_URL', default='http://localhost:8000')
#: O token que o Google Search Console pede para provar que o domínio é
#: nosso. Vazio -- o padrão -- simplesmente não emite a meta tag.
#:
#: Em variável de ambiente, e não no template, porque é por instalação:
#: quem subir o NeuroDoc no próprio domínio tem outro token, e deixá-lo
#: no HTML versionado faria toda instalação declarar a propriedade da
#: nossa. Depois de verificado, o token pode ficar: o Google revalida de
#: tempos em tempos e a propriedade cai se a tag sumir.
GOOGLE_SITE_VERIFICATION = env('GOOGLE_SITE_VERIFICATION', default='')
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = env('TIME_ZONE', default='America/Sao_Paulo')
USE_I18N = True
USE_TZ = True
ROOT_URLCONF = 'core.urls'
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL = 'accounts.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = '/accounts/select-organization/'
LOGOUT_REDIRECT_URL = 'accounts:login'
DJ_CONTROL_ROOM_BASE_SETTINGS = {'REQUIRE_SUPERUSER': True}
DJ_CONTROL_ROOM_SETTINGS = {'REQUIRE_SUPERUSER': True}
DJ_CELERY_PANEL_SETTINGS = {'REQUIRE_SUPERUSER': True}
INSTALLED_APPS = [
    'base.admin.TechnicalAdminConfig', 'django.contrib.auth',
    'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles',
    'django.contrib.postgres', 'django_otp',
    'django_otp.plugins.otp_totp',
    'dj_control_room_base', 'dj_celery_panel', 'dj_control_room',
    'base', 'accounts', 'tenancy', 'patients',
    'catalogs', 'clinical', 'scheduling', 'documents', 'communications',
    'finance', 'ai', 'notifications', 'audit', 'reporting',
    'integrations', 'events', 'exams', 'teamchat', 'sncr', 'modelos', 'tiss', 'agenda_exames',
]
MIDDLEWARE = [
    'ops.http_health.HealthMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'ops.staticfiles.ReleaseStaticMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'base.middleware.TechnicalPanelMFAMiddleware',
    'tenancy.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Por último de propósito: o cabeçalho é posto na resposta já pronta,
    # e o nonce tem de existir antes da view — que é o que o `__call__`
    # deste middleware garante, sorteando na entrada e carimbando na saída.
    'base.csp.ContentSecurityPolicyMiddleware',
]

# --------------------------------------------------------------------------
# Política de conteúdo
# --------------------------------------------------------------------------
# **Começa em modo de relatório.** Política aplicada de saída quebra em
# silêncio e de longe: o navegador não executa, e a tela que falha é a que
# ninguém abriu na semana da publicação. Em modo de relatório o navegador
# obedece normalmente e **avisa** o que teria bloqueado — colhe-se o
# inventário real, com o sistema em uso, e só então se fecha.
#
# Ligar é uma variável e um redeploy, e desligar tem o mesmo custo. Ver
# `base/csp.py` para as diretivas e o porquê de cada uma.
CSP_ENFORCE = env.bool('CSP_ENFORCE', default=False)
CSP_REPORT_URI = env('CSP_REPORT_URI', default='/csp-report/')
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'base.context_processors.shell',
        'base.csp.csp_nonce',
        # Título, descrição, canônica, Open Graph e dados estruturados.
        # Em processador de contexto, e não em cada view, porque o que
        # ele tem de garantir é o **negativo**: toda página que não está
        # no catálogo de `base/seo.py` sai com `noindex`. Posto view a
        # view, a tela esquecida seria a indexada.
        'base.seo.contexto',
    ]},
}]
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
database = {
    'ENGINE': 'django.db.backends.postgresql',
    'HOST': env('DB_HOST', default='db'), 'PORT': '5432',
    'NAME': 'neurodoc', 'CONN_MAX_AGE': 0, 'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': 5},
}
DATABASES = {'default': dict(
    database, USER='neurodoc_app', PASSWORD=secret('DB_APP_PASSWORD'),
)}
if env.bool('RUN_MIGRATIONS', default=False):
    DATABASES['migrations'] = dict(
        database, USER='neurodoc_owner', PASSWORD=secret('DB_OWNER_PASSWORD'),
    )
redis_password = quote(secret('REDIS_PASSWORD'), safe='')
rabbit_password = quote(secret('RABBITMQ_PASSWORD'), safe='')
REDIS_BASE = f'redis://:{redis_password}@redis:6379'
CELERY_BROKER_URL = f'amqp://neurodoc:{rabbit_password}@rabbitmq:5672/neurodoc'
CELERY_RESULT_BACKEND = f'{REDIS_BASE}/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_RESULT_EXPIRES = 86400
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_CONNECTION_MAX_RETRIES = 100
CELERY_BROKER_TRANSPORT_OPTIONS = {'confirm_publish': True}
CELERY_TASK_DEFAULT_QUEUE = 'maintenance'
CELERY_TASK_DEFAULT_DELIVERY_MODE = 'persistent'
CELERY_TASK_SEND_SENT_EVENT = False
CELERY_WORKER_SEND_TASK_EVENTS = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 360
# Domain tasks register routes and periodic entries during their sprints.
CELERY_TASK_ROUTES = {
    'communications.tasks.*': {'queue': 'communications'},
    'ai.tasks.*': {'queue': 'ai'},
    'documents.tasks.*': {'queue': 'documents'},
    'reporting.tasks.*': {'queue': 'documents'},
    'tiss.tasks.*': {'queue': 'documents'},
}
CELERY_BEAT_SCHEDULE = {
    # SNCR: pedido de numeração parado em "enviando" (o app caiu no meio
    # da chamada) vira incerto. Não fala com a Anvisa; só banco.
    # TISS (1.30): lote em "gerando" cuja mensagem se perdeu é reenviado.
    # A geração é idempotente; só banco e disco, sem rede.
    'tiss-lotes-parados': {
        'task': 'tiss.tasks.retomar_lotes_parados',
        'schedule': 300.0,
    },
    'sncr-pedidos-parados': {
        'task': 'sncr.tasks.marcar_pedidos_parados',
        'schedule': 300.0,
    },
    # Espelho da TUSS: domingo, 04h. A tabela muda por resolucao normativa
    # -- semanas ou meses --, entao semanal sobra; o que nao pode e nunca
    # atualizar. Roda no worker, que e quem tem saida para a internet.
    'sync-tuss': {
        'task': 'catalogs.tasks.sync_tuss',
        'schedule': crontab(hour=4, minute=0, day_of_week=0),
    },
    # Operadoras ativas da ANS (1.30), para o cadastro de convênio:
    # segunda-feira, 05h. A ANS atualiza a lista quando uma operadora
    # entra ou sai do mercado -- semanal sobra.
    'importar-operadoras-ans': {
        'task': 'catalogs.tasks.importar_operadoras_ans',
        'schedule': crontab(hour=5, minute=0, day_of_week=1),
    },
    # Retomada do que ficou pela metade: de hora em hora.
    #
    # A sincronizacao avanca em rodadas e cada uma agenda a seguinte ao
    # terminar. Um deploy no meio de uma rodada derruba o worker, a rodada
    # morre sem agendar nada, e o laco acaba em silencio -- a tabela
    # simplesmente para de crescer. Aconteceu: parou em 3.200 de ~5.900 e
    # so voltou com disparo manual, dias depois.
    #
    # De hora em hora, e nao de minuto em minuto: a tarefa so faz trabalho
    # quando ha release em rascunho, e uma tabela que demora mais uma hora
    # para fechar nao prejudica ninguem -- a busca continua respondendo
    # pela release anterior enquanto isso.
    'retomar-tuss-incompleta': {
        'task': 'catalogs.tasks.retomar_tuss_incompleta',
        'schedule': crontab(minute=20),
    },
    # Compactação do arquivo morto: 03h do dia 1 de janeiro, abril, julho e
    # outubro. `crontab` e não intervalo em segundos porque "a cada 90 dias"
    # a partir do último reinício do beat cairia em qualquer hora do dia —
    # e isto é trabalho de disco que não deve disputar E/S com o
    # atendimento.
    'documents-compact-archive': {
        'task': 'documents.tasks.compact_archive',
        'schedule': crontab(minute=0, hour=3, day_of_month=1, month_of_year='1,4,7,10'),
    },
    'documents-update-clamav-definitions': {
        'task': 'documents.tasks.update_clamav_definitions',
        'schedule': 6 * 60 * 60,
    },
    'events-dispatch-outbox': {
        'task': 'events.tasks.dispatch_outbox',
        'schedule': 5,
    },
    # Job de IA que ficou "na fila" sem chegar ao worker. Dez minutos
    # porque o corte e de vinte: ninguem espera mais que meia hora por um
    # job perdido. Ver `ai.tasks.retomar_jobs_parados`.
    'ai-retomar-jobs-parados': {
        'task': 'ai.tasks.retomar_jobs_parados',
        'schedule': 600,
    },
    # A IA da instalação conferida de hora em hora, com e-mail ao
    # superadministrador quando falha. A verificação existia só no botão do
    # console, e foi assim que o modelo aposentado em 2026 ficou quarenta
    # dias sem ninguém saber. Minuto 47 para não coincidir com as outras
    # rodadas de hora cheia. Ver `ai.tasks.vigiar_ia_da_instalacao`.
    'ai-vigiar-ia-da-instalacao': {
        'task': 'ai.tasks.vigiar_ia_da_instalacao',
        'schedule': crontab(minute=47),
    },
    'communications-reconcile-pending-sms': {
        'task': 'communications.tasks.reconcile_pending_sms',
        'schedule': 60,
    },
    # Avisos e diagnósticos de transporte são dados transitórios. A trilha
    # permanente continua nos objetos de origem e em `audit`; conservar estas
    # caixas indefinidamente só aumenta o banco e repete identificação de
    # paciente sem finalidade operacional.
    # Aviso de retorno previsto: todo dia as 6h.
    #
    # Cedo, e antes do expediente: o e-mail chega antes de a pessoa comecar
    # o dia, e a rodada termina muito antes de a clinica abrir -- disputar
    # CPU com o atendimento seria o pior momento possivel.
    #
    # Diaria e nao semanal porque o corte e por data: um retorno vence num
    # dia especifico, e uma rodada semanal avisaria alguns com vinte dias e
    # outros com quatorze, sem que ninguem soubesse por que.
    'scheduling-avisar-retornos': {
        'task': 'scheduling.tasks.avisar_retornos',
        'schedule': crontab(hour=6, minute=0),
    },
    # Chat da equipe: mensagem vive 72 horas (teamchat/services.py). De
    # hora em hora, para o prazo prometido na janela ser o prazo cumprido.
    'teamchat-apagar-vencidas': {
        'task': 'teamchat.tasks.apagar_vencidas',
        'schedule': crontab(minute=35),
    },
    'notifications-purge-expired': {
        'task': 'notifications.tasks.purge_expired',
        'schedule': crontab(hour=1, minute=10),
    },
    'communications-purge-expired': {
        'task': 'communications.tasks.purge_expired',
        'schedule': crontab(hour=1, minute=20),
    },
    'reporting-expire-exports': {
        'task': 'reporting.tasks.expire_exports',
        'schedule': 300,
    },
    # Coleta do arquivo de anexo ja apagado: domingo, 02h.
    #
    # Semanal e nao diaria porque ela segura a trava do backup enquanto roda,
    # e a janela do backup e noturna; domingo 02h e o vale entre as duas.
    # Comeca em ENSAIO (`DOCUMENTS_GC_DRY_RUN=True`): conta e registra, nao
    # apaga. Ver `documents/tasks.py::garbage_collect_task`.
    'documents-garbage-collect': {
        'task': 'documents.tasks.garbage_collect',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),
    },
}

# Ensaio da coleta de lixo. `True` conta e registra sem apagar.
#
# Vira `False` por `.env`, e nao por commit: autorizar apagamento permanente
# de arquivo clinico e decisao do controlador. Ligue **depois** de um mes de
# ensaio e **depois** de a restauracao do backup ter sido testada num host
# separado -- apagar so e seguro quando se provou que se sabe restaurar.
DOCUMENTS_GC_DRY_RUN = env.bool('DOCUMENTS_GC_DRY_RUN', default=True)
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
    'LOCATION': f'{REDIS_BASE}/1', 'TIMEOUT': 900,
    'KEY_PREFIX': 'neurodoc',
}}
AI_EVENTS_REDIS_URL = f'{REDIS_BASE}/2'
# Banco próprio para o chat da equipe: presença e caixas de entrada são
# efêmeras e de alto giro, e um `FLUSHDB` de emergência num deles não pode
# derrubar o streaming da IA (nem o cache) junto.
TEAMCHAT_REDIS_URL = f'{REDIS_BASE}/3'
RELEASE_ID = env('RELEASE_ID', default='dev')
if not re.fullmatch(r'(dev|[a-f0-9]{40})', RELEASE_ID):
    raise ValueError('Invalid RELEASE_ID')
STATIC_URL = f'/static/{RELEASE_ID}/'
STATIC_ROOT = Path(os.environ.get('STATIC_PREPARATION_ROOT', '/data/staticfiles/public/static/' + RELEASE_ID))
STATICFILES_DIRS = [BASE_DIR / 'static']
WHITENOISE_AUTOREFRESH = False
WHITENOISE_USE_FINDERS = False
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
MEDIA_ROOT = Path('/data/media')
MEDIA_URL = '/private-media-unrouted/'
PFX_ROOT = Path('/data/signing')
SIGNING_SESSION_KEY_ROOT = Path('/run/neurodoc-signing')
PFX_MASTER_KEY = secret('PFX_MASTER_KEY', required=False)

# Chave-mestra dos segredos que a clínica configura pela tela (chave do
# SMSDEV, senha de SMTP do médico). Separada da do PFX de propósito:
# comprometer a chave de SMS não deveria dar acesso ao certificado de
# assinatura. Enquanto não for definida, `base.crypto` cai na do PFX para a
# instalação existente continuar funcionando, e a tela avisa que estão
# compartilhadas.
SECRETS_MASTER_KEY = secret('SECRETS_MASTER_KEY', required=False)
DATA_UPLOAD_MAX_MEMORY_SIZE = 26214400
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REDIRECT_EXEMPT = [r'^health/$']
# HSTS: ligado por configuracao, e nao por commit.
#
# Zero e o padrao de proposito. HSTS diz ao navegador "nunca mais fale com
# este dominio em HTTP", e ele **guarda isso**: ligar antes de o HTTPS
# estar comprovadamente funcionando deixa o site inalcancavel para quem ja
# visitou, e nao ha como voltar atras no navegador dessa pessoa.
#
# O caminho e ligar depois do primeiro deploy, com o certificado emitido e
# o dominio respondendo -- e por isso a variavel esta no `.env`, para essa
# virada nao exigir uma nova imagem.
#
# Valor recomendado depois da validacao: 31536000 (um ano). Sub-dominios
# so quando todos os aliases tiverem TLS proprio.
# HSTS: o padrao continua `0`, e isso e decisao, nao esquecimento.
#
# O navegador **guarda** a instrucao e nao ha como voltar atras: ligar
# antes de o HTTPS estar comprovadamente no ar deixa o dominio inacessivel
# ate o certificado funcionar. Uma instalacao nova, por definicao, ainda
# nao comprovou nada -- entao o padrao de quem instala hoje tem de ser o
# seguro, e ligar e um ato explicito de quem ja viu o cadeado funcionando.
#
# A instalacao de producao (neurodoc.app.br) ligou em 02/10/2026, com um
# ano, depois de uma semana de HTTPS estavel: `SECURE_HSTS_SECONDS` no
# `.env` dela. Ver `docs/operations/manutencao.md`.
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = 'Lax'
#: A recusa por token CSRF tem tela propria (`base/csrf.py`).
#:
#: O padrao do Django e um 403 sem estilo nem saida, e ele aparece na
#: situacao mais banal que existe: sair do sistema e entrar de novo na aba
#: que ja estava aberta. `auth_login` troca o cookie CSRF, o formulario que
#: ficou na aba carrega o token de antes, e o servidor recusa -- com uma
#: pagina que nao diz o que fazer.
CSRF_FAILURE_VIEW = 'base.csrf.csrf_failure'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
EMAIL_ENABLED = env.bool('EMAIL_ENABLED', default=False)
# Ligado, o e-mail sai pela fila -- nunca pelo SMTP daqui.
#
# Quem entrega e o worker, por tres razoes: so a ele o segredo de SMTP e
# entregue, ele pode tentar de novo quando o provedor falha, e ninguem
# fica esperando. Falar com o SMTP dentro da requisicao travaria dez
# segundos no `EMAIL_TIMEOUT` em todo cadastro e em toda recuperacao de
# senha. Veja `communications/mail_backend.py`.
#
# Quem entrega e `communications.tasks.deliver_installation_email`, que
# pede o backend SMTP **explicitamente** -- ler esta variavel la faria a
# mensagem voltar para a fila indefinidamente.
EMAIL_BACKEND = (
    'communications.mail_backend.WorkerEmailBackend' if EMAIL_ENABLED
    else 'django.core.mail.backends.locmem.EmailBackend'
)
EMAIL_HOST = env('EMAIL_HOST', default='smtp.example.invalid')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = secret('SMTP_PASSWORD', required=(EMAIL_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
# Duas formas de cifrar a conversa com o SMTP, e elas nao sao
# intercambiaveis -- e por isso ha duas variaveis, e nao uma.
#
# STARTTLS (`EMAIL_USE_TLS`): conecta em claro na porta 587 e pede para
# subir para TLS. SSL implicito (`EMAIL_USE_SSL`): a conexao ja nasce
# cifrada, na porta 465.
#
# Errar isso nao da erro de configuracao: da **espera**. Pedir STARTTLS
# numa porta 465 deixa o cliente aguardando um banner que nunca vem, ate
# o `EMAIL_TIMEOUT` de dez segundos -- e o sintoma que chega ao suporte e
# "o e-mail nao sai", sem nada no log dizendo por que. Por isso as duas
# combinacoes impossiveis levantam aqui, na subida do processo, onde a
# mensagem diz o que fazer:
# Os dois padroes sao `False` -- "nao configurado", e nao um palpite. Um
# padrao verdadeiro aqui escolheria a cifragem no lugar de quem instala, e
# a escolha errada e silenciosa. O `.env.example` traz os valores reais
# desta instalacao, e a checagem abaixo recusa deixar o campo em branco
# quando o envio esta ligado.
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=False)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ValueError(
        'EMAIL_USE_TLS e EMAIL_USE_SSL sao alternativos: ligue apenas um. '
        'Porta 587 usa EMAIL_USE_TLS=True; porta 465 usa EMAIL_USE_SSL=True.'
    )
if EMAIL_ENABLED and not EMAIL_USE_TLS and not EMAIL_USE_SSL and EMAIL_PORT in (465, 587):
    raise ValueError(
        f'EMAIL_PORT={EMAIL_PORT} sem cifragem. Ligue EMAIL_USE_SSL=True para a '
        'porta 465, ou EMAIL_USE_TLS=True para a 587. Enviar credencial de SMTP '
        'em claro entrega a senha da conta de e-mail a quem estiver na rede.'
    )
if EMAIL_ENABLED and EMAIL_PORT == 465 and EMAIL_USE_TLS:
    raise ValueError(
        'EMAIL_PORT=465 com EMAIL_USE_TLS=True nao conecta: a 465 e SSL '
        'implicito, e o pedido de STARTTLS fica esperando um banner que nunca '
        'chega, ate o timeout. Use EMAIL_USE_SSL=True e EMAIL_USE_TLS=False.'
    )
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
SERVER_EMAIL = env('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)
ADMINS = [(f'ops-{i}', addr) for i, addr in enumerate(env.list('ALERT_ADMIN_EMAILS', default=[]))]
MANAGERS = ADMINS
DEFAULT_EXCEPTION_REPORTER_FILTER = 'base.logging.NoPostDataExceptionReporterFilter'
# O filtro decide o que de cada secao e mostrado; o reporter decide quais
# secoes existem. A query string so se tira aqui -- ver a classe.
DEFAULT_EXCEPTION_REPORTER = 'base.logging.NoQueryStringExceptionReporter'
# Destinatario dos pedidos de contato da pagina de vendas.
#
# Fixo na configuracao, nunca um campo do formulario: formulario publico
# que aceita destinatario do cliente e um relay aberto -- qualquer um
# mandaria mensagem com o remetente do dominio da clinica para qualquer
# endereco, e o dominio pagaria a reputacao.
LEADS_EMAIL = env('LEADS_EMAIL', default='contato@neurodoc.app.br')
SMS_ENABLED = env.bool('SMS_ENABLED', default=False)
SMSDEV_API_KEY = secret('SMSDEV_API_KEY', required=(SMS_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
AI_ENABLED = env.bool('AI_ENABLED', default=False)
AI_PROVIDER = env('AI_PROVIDER', default='nvidia')
AI_MODEL = env('AI_MODEL', default='nvidia/llama-3.3-nemotron-super-49b-v1.5')
# Chave do provedor **da instalação**, resolvida pelo nome dele.
#
# Uma só, e derivada, em vez de uma constante por provedor. Havia três
# (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), e era esse
# trio que limitava o padrão da instalação a três dos dez provedores do
# catálogo — acrescentar um exigia editar settings, o mapa de getters e o
# `docker-stack.yml`, e esquecer qualquer um dos três dava "Unknown AI
# provider" para uma configuração que a tela oferecia.
#
# Assim, habilitar um provedor novo como padrão é gravar o secret com o
# nome dele e apontar `AI_PROVIDER`. A chave da **clínica** não passa por
# aqui: fica cifrada no banco (`ai.models.AIProviderSettings`).
AI_API_KEY = secret(f'{AI_PROVIDER.upper()}_API_KEY', required=False)
# Enderecos de API que esta instalacao libera **alem** dos provedores do
# catalogo. Vazio -- o padrao -- significa "so os do catalogo", e e a
# resposta certa para quem usa provedor publico.
#
# Existe porque o campo "endereco da API" da tela da clinica aceita servidor
# proprio (Ollama, vLLM), e o processo `app` alcanca a rede interna -- e
# tambem a internet, pela `traefik_public`. Sem lista, um gestor de clinica
# apontava o campo para `http://169.254.169.254/` e o servidor ia la por
# ele, com rota de saida para mandar o resultado adiante.
#
# Quem libera e quem opera o servidor, e nao o cliente -- e a rede dele que
# sera alcancada. Um host por entrada: `AI_BASE_URL_ALLOWLIST=ollama.interno,10.0.0.7:11434`
AI_BASE_URL_ALLOWLIST = env.list('AI_BASE_URL_ALLOWLIST', default=[])
NEURODOC_DEMO_ALLOWED = env.bool('NEURODOC_DEMO_ALLOWED', default=False)
NEURODOC_RECOVERY_MODE = env.bool('NEURODOC_RECOVERY_MODE', default=False)
NEURODOC_DOCS_ENABLED = env.bool('NEURODOC_DOCS_ENABLED', default=True)
# Never log request bodies; base.logging.RedactSensitiveDataFilter strips
# password/token/secret-like values from every record on the console handler.
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'filters': {'redact_sensitive': {'()': 'base.logging.RedactSensitiveDataFilter'}},
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'filters': ['redact_sensitive']},
        # Alert recipients (ALERT_ADMIN_EMAILS) get an e-mail for every
        # unhandled 5xx, through the same redaction filter -- so an alert
        # can carry a stack trace/request path, never a clinical payload.
        'mail_admins': {
            'class': 'django.utils.log.AdminEmailHandler', 'level': 'ERROR', 'filters': ['redact_sensitive'],
        },
    },
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {
        'django.security.DisallowedHost': {
            'handlers': ['console'], 'level': 'ERROR', 'propagate': False,
        },
        'django.request': {
            'handlers': ['console', 'mail_admins'], 'level': 'ERROR', 'propagate': False,
        },
    },
}
