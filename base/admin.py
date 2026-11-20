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

    def login(self, request, extra_context=None):
        """O admin entra pela porta que pede o código, e só por ela.

        O `AdminSite.login` do Django confere a senha e chama `auth_login`
        sem segundo fator. O conteúdo do admin continuava fechado
        (`has_permission` exige `is_verified()`), mas a sessão só com a
        senha valia no resto do sistema — e, somada à tela de configurar o
        segundo fator, virava o console inteiro (auditoria externa de
        2026-11-20). Agora o endereço do admin manda ao login do produto.
        """
        from django.shortcuts import redirect
        from django.urls import reverse
        from django.utils.http import url_has_allowed_host_and_scheme, urlencode

        destino = request.GET.get('next') or reverse('admin:index')
        if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
            destino = reverse('admin:index')
        return redirect(f'{reverse("accounts:login")}?{urlencode({"next": destino})}')

    def has_permission(self, request):
        user = request.user
        return bool(
            user.is_authenticated and user.is_active and user.is_staff
            and user.is_superuser and user.is_verified()
        )


class SemConteudoClinicoAdmin(admin.ModelAdmin):
    """A lista do admin mostra a linha; o registro aberto, nunca.

    `ops/superadmin.py` fixa o princípio: quem opera o servidor sabe *quem
    fez o quê*, e ler prontuário exige vínculo clínico — que aparece na
    trilha. O admin do Django furava isso em silêncio: o superusuário tem
    permissão de **ver** por padrão, a tela de detalhe mostra todos os
    campos (queixa, história, conduta, a resposta da IA, o corpo da
    receita) de todas as clínicas, e nada disso passava por
    `record_audit_event` — o `LogEntry` do Django só registra alteração.
    Somente-leitura bloqueava escrever, não ler (achado de
    @meirakalile-ship-it, 2026-11-17).

    A recusa é **por registro** (`obj` presente), e não do modelo inteiro:
    a lista continua respondendo "existe esta linha, de que clínica, em que
    estado?", com colunas escolhidas para não trazer texto clínico. Quem
    precisa ler o conteúdo entra pela clínica, com vínculo, e fica na
    trilha. Auditar a leitura pelo admin foi a alternativa recusada: o
    registro diria que o sigilo foi quebrado, não impediria a quebra.
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        if obj is not None:
            return False
        return super().has_view_permission(request, obj)


class TechnicalAdminConfig(AdminConfig):
    default_site = 'base.admin.TechnicalAdminSite'
