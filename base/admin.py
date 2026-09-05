from django.contrib import admin
from django.contrib.admin.apps import AdminConfig


class TechnicalAdminSite(admin.AdminSite):
    site_header = 'NeuroDoc — Administração técnica'
    site_title = 'NeuroDoc admin'
    index_title = 'Administração técnica'

    def has_permission(self, request):
        user = request.user
        return bool(
            user.is_authenticated and user.is_active and user.is_staff
            and user.is_superuser and user.is_verified()
        )


class TechnicalAdminConfig(AdminConfig):
    default_site = 'base.admin.TechnicalAdminSite'
