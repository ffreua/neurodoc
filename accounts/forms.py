from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import throttling
from base.net import client_ip


class ThrottledAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self._client_ip = client_ip(request) if request else None

    def clean(self):
        email = self.cleaned_data.get('username')
        if email and throttling.is_throttled(email, self._client_ip):
            raise ValidationError('Too many attempts. Try again later.', code='throttled')
        if email:
            throttling.apply_progressive_delay(email, self._client_ip)
        try:
            return super().clean()
        except ValidationError:
            if email:
                throttling.register_failure(email, self._client_ip)
            raise


class ThrottledAdminAuthenticationForm(ThrottledAuthenticationForm, AdminAuthenticationForm):
    """A porta de `/admin/login/` com o mesmo limitador da porta da frente.

    `/accounts/login/` conta tentativa errada, aplica atraso progressivo e
    bloqueia. `/admin/login/` nao passava por nada disso: ele usa o
    formulario do proprio Django, e o limitador da casa vive no formulario
    acima, que so a view de `/accounts/` instancia. A conta de
    superadministrador -- a unica que abre `/instalacao/` e os paineis
    tecnicos -- era justamente a que podia ter a senha tentada sem limite
    e sem deixar rastro.

    A MFA continua barrando o conteudo (`base.admin.TechnicalAdminSite`
    exige `is_verified()`), entao isto nunca foi entrada franca; o que
    faltava era a contagem.

    Herdar dos dois mantem as duas garantias: o `clean` com limitador vem
    de `ThrottledAuthenticationForm`, e a recusa de quem nao e `is_staff`
    vem de `AdminAuthenticationForm`, que `AuthenticationForm.clean`
    alcanca por `confirm_login_allowed`.

    Mora aqui, e nao em `base/admin.py`, porque aquele modulo e carregado
    pelo `AdminConfig` **durante** a carga dos apps: importar
    `django.contrib.admin.forms` la puxa `django.contrib.auth.models` antes
    de o registro de apps estar pronto, e o processo nao sobe
    (`AppRegistryNotReady`). Este modulo so e importado quando uma view
    precisa dele.
    """


class MFAChallengeForm(forms.Form):
    code = forms.CharField(max_length=32, label='Código de autenticação')
