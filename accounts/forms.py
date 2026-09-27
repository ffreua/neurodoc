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


class MinhaContaForm(forms.ModelForm):
    """Nome e sobrenome da própria conta.

    Existiu uma lacuna aqui: `first_name` e `last_name` só se preenchiam
    pelo admin técnico do Django, que é de quem opera o servidor. Quem se
    cadastrava ficava com a conta sem nome, e as telas que mostram pessoa
    passavam a estampar o **endereço de e-mail** no lugar do nome. Para o
    médico, `PhysicianProfile.professional_name` cobre o buraco; para a
    secretária e para quem administra, não havia nada.

    Só estes dois campos, e de propósito. O e-mail é a identidade de
    login, e trocá-lo é outro procedimento — envolve reverificação, porque
    é para onde vão a recuperação de senha e a via do contrato. Um
    `<input>` de e-mail nesta tela convidaria a uma troca que ela não sabe
    concluir com segurança.
    """

    class Meta:
        from .models import User

        model = User
        fields = ['first_name', 'last_name']
        labels = {'first_name': 'Nome', 'last_name': 'Sobrenome'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['first_name'].widget.attrs.update({'autocomplete': 'given-name'})
        self.fields['last_name'].widget.attrs.update({'autocomplete': 'family-name'})
        self.fields['last_name'].help_text = 'Opcional.'

    def clean_first_name(self):
        """Espaço em branco não é nome.

        Sem isto, `'   '` passaria na exigência de preenchimento, seria
        gravado, e `get_full_name` voltaria a cair no e-mail — com a tela
        dizendo que salvou.
        """
        valor = (self.cleaned_data.get('first_name') or '').strip()
        if not valor:
            raise ValidationError('Informe ao menos o primeiro nome.')
        return valor

    def clean_last_name(self):
        return (self.cleaned_data.get('last_name') or '').strip()
