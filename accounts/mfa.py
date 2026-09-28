import base64
import secrets
from functools import wraps

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.http import HttpResponseForbidden
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

RECENT_MFA_SESSION_KEY = 'mfa_verified_at'
RECENT_MFA_MAX_AGE_SECONDS = 1800
RECOVERY_CODE_COUNT = 10


def qr_code_data_uri(payload):
    """Transforma a chave TOTP em um QR local, sem entregar o segredo.

    Gerar a imagem num servico de QR externo parece simples, mas a URL
    ``otpauth://`` contem a chave que produz todos os codigos futuros. Uma
    requisicao para esse servico entregaria o segundo fator a um terceiro.

    O ReportLab ja faz parte da aplicacao para os QR dos documentos. A
    matriz vira um SVG compacto em uma ``data:`` URI: o navegador recebe a
    imagem no proprio HTML e nao faz nenhuma requisicao com o segredo.
    """
    from reportlab.graphics.barcode.qr import QrCodeWidget

    widget = QrCodeWidget(payload, barLevel='M')
    # O ReportLab so monta a matriz quando calcula os limites do widget.
    # Ler `modules` antes disso devolve None, embora o objeto ja exista.
    widget.getBounds()
    modules = widget.qr.modules
    border = 4
    side = len(modules) + (border * 2)
    commands = []
    for row_index, row in enumerate(modules):
        column = 0
        while column < len(row):
            if not row[column]:
                column += 1
                continue
            start = column
            while column < len(row) and row[column]:
                column += 1
            length = column - start
            commands.append(
                f'M{start + border} {row_index + border}h{length}v1h-{length}z'
            )
    path = ''.join(commands)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}" '
        f'shape-rendering="crispEdges"><rect width="{side}" height="{side}" fill="#fff"/>'
        f'<path d="{path}" fill="#111827"/></svg>'
    )
    encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'


def get_confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).first()


def user_has_confirmed_totp(user):
    return get_confirmed_device(user) is not None


def get_or_create_pending_device(user):
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, confirmed=False)
    return device


def confirm_device(device, token):
    if device.verify_token(token):
        device.confirmed = True
        device.save(update_fields=['confirmed'])
        return True
    return False


def verify_totp_token(user, token):
    device = get_confirmed_device(user)
    return device is not None and device.verify_token(token)


def generate_recovery_codes(user, count=RECOVERY_CODE_COUNT):
    from .models import RecoveryCode

    with transaction.atomic():
        RecoveryCode.objects.filter(user=user, used_at=None).delete()
        raw_codes = []
        for _ in range(count):
            raw = secrets.token_hex(5)
            raw_codes.append(raw)
            RecoveryCode.objects.create(user=user, code_hash=make_password(raw))
    return raw_codes


@transaction.atomic
def consume_recovery_code(user, raw_code):
    from .models import RecoveryCode

    candidates = (
        RecoveryCode.objects
        .select_for_update()
        .filter(user=user, used_at=None)
    )
    for candidate in candidates:
        if check_password(raw_code, candidate.code_hash):
            candidate.used_at = timezone.now()
            candidate.save(update_fields=['used_at'])
            return True
    return False


def mark_recent_mfa(request):
    request.session[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()


def mfa_verified_recently(request, max_age_seconds=RECENT_MFA_MAX_AGE_SECONDS):
    stamp = request.session.get(RECENT_MFA_SESSION_KEY)
    if not stamp:
        return False
    verified_at = timezone.datetime.fromisoformat(stamp)
    if timezone.is_naive(verified_at):
        verified_at = timezone.make_aware(verified_at)
    return (timezone.now() - verified_at).total_seconds() < max_age_seconds


def require_recent_mfa(view_func):
    """View decorator for privileged operations: require a fresh MFA check."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not mfa_verified_recently(request):
            return HttpResponseForbidden('Recent MFA verification required.')
        return view_func(request, *args, **kwargs)

    return wrapper
