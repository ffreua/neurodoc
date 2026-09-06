from django.contrib import admin

from .models import Invitation, Membership, Tenant, TenantDomain


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['legal_name', 'cnpj', 'slug', 'status', 'plan']
    search_fields = ['legal_name', 'trade_name', 'cnpj', 'slug']
    exclude = ['settings']


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'tenant', 'is_primary', 'verified_at']
    search_fields = ['hostname']


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'tenant', 'roles', 'status', 'activated_at', 'revoked_at']
    list_filter = ['status', 'tenant']
    search_fields = ['user__email', 'tenant__legal_name']


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ['purpose', 'target_tenant', 'email_binding', 'expires_at', 'consumed_at', 'revoked_at']
    list_filter = ['purpose']
    exclude = ['token_hash']
