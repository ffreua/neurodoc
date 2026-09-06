import os
import re
from pathlib import Path
from urllib.parse import quote

import environ

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
PUBLIC_BASE_URL = env('PUBLIC_BASE_URL', default='http://localhost:8000')
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = env('TIME_ZONE', default='America/Sao_Paulo')
USE_I18N = True
USE_TZ = True
ROOT_URLCONF = 'core.urls'
ASGI_APPLICATION = 'core.asgi.application'
AUTH_USER_MODEL = 'accounts.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = '/app/'
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
    'crm', 'finance', 'ai', 'notifications', 'audit', 'reporting',
    'integrations', 'events',
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
]
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
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
}
CELERY_BEAT_SCHEDULE = {
    'documents-update-clamav-definitions': {
        'task': 'documents.tasks.update_clamav_definitions',
        'schedule': 6 * 60 * 60,
    },
    'events-dispatch-outbox': {
        'task': 'events.tasks.dispatch_outbox',
        'schedule': 5,
    },
    'communications-reconcile-pending-sms': {
        'task': 'communications.tasks.reconcile_pending_sms',
        'schedule': 60,
    },
}
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
    'LOCATION': f'{REDIS_BASE}/1', 'TIMEOUT': 900,
    'KEY_PREFIX': 'neurodoc',
}}
AI_EVENTS_REDIS_URL = f'{REDIS_BASE}/2'
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
DATA_UPLOAD_MAX_MEMORY_SIZE = 26214400
FILE_UPLOAD_MAX_MEMORY_SIZE = 1048576
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REDIRECT_EXEMPT = [r'^health/$']
SECURE_HSTS_SECONDS = 0
# Enable after staging validation: 31536000, then includeSubDomains if all aliases use TLS.
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
EMAIL_ENABLED = env.bool('EMAIL_ENABLED', default=False)
EMAIL_BACKEND = (
    'django.core.mail.backends.smtp.EmailBackend' if EMAIL_ENABLED
    else 'django.core.mail.backends.locmem.EmailBackend'
)
EMAIL_HOST = env('EMAIL_HOST', default='smtp.example.invalid')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = secret('SMTP_PASSWORD', required=(EMAIL_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
SERVER_EMAIL = env('SERVER_EMAIL', default=DEFAULT_FROM_EMAIL)
ADMINS = [(f'ops-{i}', addr) for i, addr in enumerate(env.list('ALERT_ADMIN_EMAILS', default=[]))]
MANAGERS = ADMINS
DEFAULT_EXCEPTION_REPORTER_FILTER = 'base.logging.NoPostDataExceptionReporterFilter'
SMS_ENABLED = env.bool('SMS_ENABLED', default=False)
SMSDEV_API_KEY = secret('SMSDEV_API_KEY', required=(SMS_ENABLED and env('SERVICE_ROLE', default='app') == 'worker'))
AI_ENABLED = env.bool('AI_ENABLED', default=False)
AI_PROVIDER = env('AI_PROVIDER', default='openrouter')
AI_MODEL = env('AI_MODEL', default='z-ai/glm-5.3-flash')
OPENROUTER_API_KEY = secret('OPENROUTER_API_KEY', required=False)
OPENAI_API_KEY = secret('OPENAI_API_KEY', required=False)
ANTHROPIC_API_KEY = secret('ANTHROPIC_API_KEY', required=False)
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
