from django.contrib import admin

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
class MessageAdmin(admin.ModelAdmin):
    """Sem `list_display` do corpo, e sem busca por ele.

    A listagem do admin é uma tela de suporte técnico, e o corpo da
    mensagem é conversa entre duas pessoas da clínica — que pode citar
    paciente. Mostrar o texto numa grade paginada transformaria manutenção
    de rotina em leitura de correspondência alheia. Quem precisa de uma
    mensagem específica abre o registro; quem precisa saber que houve
    acesso tem a trilha de auditoria.
    """

    list_display = ['sender', 'conversation', 'created_at', 'tenant']
    list_filter = ['tenant']
    search_fields = []
