from django.apps import AppConfig


#: A opção vazia de toda lista de escolha. O Django 6.1 trocou o antigo
#: "---------" por "- Select an option -", e o catálogo pt_BR dele ainda não
#: traz a tradução — a frase em inglês apareceu em toda lista de escolha de
#: modelo, a começar pela guia TISS, e foi o médico quem viu. O próprio
#: Django indica este ponto (o `ready()` de um app) para redefini-la; fazer
#: em cada formulário com `empty_label` deixaria escapar o próximo que
#: ninguém lembrasse. `check_idioma` confere que ela continua em português.
OPCAO_VAZIA = '— Selecione —'


class BaseConfig(AppConfig):
    name = 'base'

    def ready(self):
        from django.db.models import fields

        fields.BLANK_CHOICE_LABEL = OPCAO_VAZIA
