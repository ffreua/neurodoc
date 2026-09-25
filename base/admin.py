from django.contrib import admin
from django.contrib.admin.apps import AdminConfig


class TechnicalAdminSite(admin.AdminSite):
    site_header = 'NeuroDoc — Administração técnica'
    site_title = 'NeuroDoc admin'
    index_title = 'Administração técnica'

    @property
    def login_form(self):
        """Resolvida na requisicao, nao na carga.

        `AdminConfig` importa este modulo durante a carga dos apps; um
        `from accounts.forms import ...` no topo puxaria
        `django.contrib.auth.models` antes de o registro estar pronto e o
        processo nao subiria. O Django le `self.login_form` dentro de
        `AdminSite.login()`, ja em tempo de requisicao -- entao uma
        propriedade resolve sem mudar o contrato.
        """
        from accounts.forms import ThrottledAdminAuthenticationForm

        return ThrottledAdminAuthenticationForm

    def has_permission(self, request):
        user = request.user
        return bool(
            user.is_authenticated and user.is_active and user.is_staff
            and user.is_superuser and user.is_verified()
        )


class TechnicalAdminConfig(AdminConfig):
    default_site = 'base.admin.TechnicalAdminSite'
