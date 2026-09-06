from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['sanitized_title', 'user', 'kind', 'read_at', 'tenant']
    list_filter = ['kind', 'tenant']
