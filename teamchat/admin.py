from django.contrib import admin

from base.admin import SemConteudoClinicoAdmin

from .models import Conversation, ConversationMember, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'tenant', 'last_message_at', 'created_at']
    list_filter = ['tenant']


@admin.register(ConversationMember)
class ConversationMemberAdmin(admin.ModelAdmin):
    list_display = ['user', 'conversation', 'unread_count', 'last_read_at', 'tenant']
    list_filter = ['tenant']


@admin.register(Message)
class MessageAdmin(SemConteudoClinicoAdmin):
    """Sem `list_display` do corpo, e sem busca por ele.

    A listagem do admin é uma tela de suporte técnico, e o corpo da
    mensagem é conversa entre duas pessoas da clínica — que pode citar
    paciente. Mostrar o texto numa grade paginada transformaria manutenção
    de rotina em leitura de correspondência alheia. Abrir o registro também
    é recusado (`base.admin.SemConteudoClinicoAdmin`): o admin não passava
    pela trilha, e "quem precisa abre" era leitura sem rastro.
    """

    list_display = ['sender', 'conversation', 'created_at', 'tenant']
    list_filter = ['tenant']
    search_fields = []
