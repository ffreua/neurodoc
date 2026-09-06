from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import PhysicianProfile, RecoveryCode, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ['email']
    list_display = ['email', 'first_name', 'last_name', 'is_staff', 'is_active', 'email_verified_at']
    search_fields = ['email', 'first_name', 'last_name']
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Verification', {'fields': ('email_verified_at',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'password1', 'password2')}),
    )
    readonly_fields = ['last_login', 'date_joined']


@admin.register(RecoveryCode)
class RecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ['user', 'used_at', 'expires_at', 'created_at']
    fields = ['user', 'used_at', 'expires_at', 'created_at']
    readonly_fields = fields
    search_fields = ['user__email']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PhysicianProfile)
class PhysicianProfileAdmin(admin.ModelAdmin):
    list_display = ['professional_name', 'crm_number', 'crm_state', 'verification_status']
    list_filter = ['verification_status']
    search_fields = ['professional_name', 'crm_number', 'user__email']
