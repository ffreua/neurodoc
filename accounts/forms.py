from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import throttling


class ThrottledAuthenticationForm(AuthenticationForm):
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self._client_ip = request.META.get('REMOTE_ADDR') if request else None

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


class MFAChallengeForm(forms.Form):
    code = forms.CharField(max_length=32, label='Código de autenticação')
