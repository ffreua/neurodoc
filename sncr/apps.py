from django.apps import AppConfig


class SncrConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sncr'
    verbose_name = 'SNCR (numeração de receitas da Anvisa)'
