import base64
import secrets
from functools import wraps

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
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
    """Operação privilegiada: exige confirmação recente do segundo fator.

    Devolvia `403` com o texto cru numa tela branca, e em inglês. Quem
    esbarrava nele não tinha o que fazer: a mensagem não dizia para onde
    ir, e não havia para onde — a tela de reconfirmação não existia.

    Agora leva à reconfirmação e volta. O destino vai em `next` e é
    reconferido lá contra o próprio host.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not mfa_verified_recently(request):
            return redirect_to_mfa_confirm(request)
        return view_func(request, *args, **kwargs)

    return wrapper


def redirect_to_mfa_confirm(request, destino=None):
    """Manda reconfirmar o segundo fator e voltar para onde estava.

    `destino` existe para quem chega por POST: o caminho da requisição é a
    rota que recebe o formulário, e devolver a pessoa a ela por GET daria
    405. Nesses casos quem chama diz para que tela voltar.
    """
    from django.shortcuts import redirect
    from django.urls import reverse
    from django.utils.http import urlencode

    alvo = destino or request.get_full_path()
    return redirect(f'{reverse("accounts:mfa-confirm")}?{urlencode({"next": alvo})}')


# ------------------------------------------------- segundo fator obrigatório
#
# Para quem é dono ou médico numa organização ativa (revisão de 2026-11-02,
# S5). Dono pede a exportação do acervo inteiro e decide quem entra na
# equipe; médico lê e assina prontuário. Com só a senha, uma senha vazada
# bastava para as duas coisas — e 9 donos e 1 médico estavam assim em
# produção no dia da revisão.
#
# Não é "a partir de agora" para não trancar ninguém no meio de um
# atendimento: até o prazo, o aviso fica no alto de toda tela de `/app/`;
# depois dele, a entrada passa pela configuração do código antes de abrir
# qualquer tela. A secretária e o gestor ficam como estão — podem configurar,
# e não são obrigados.
#
# O prazo é por instalação (`SEGUNDO_FATOR_OBRIGATORIO_DESDE`), porque quem
# sobe uma instalação nova decide quando a equipe dela se adapta; o padrão
# do código é o desta instalação. `desligado` desliga — é como a bateria de
# roteiros roda, com usuários criados sem dispositivo; o roteiro
# `check_segundo_fator` liga a regra para conferi-la.

PAPEIS_COM_SEGUNDO_FATOR = frozenset({'owner', 'doctor'})


def prazo_do_segundo_fator():
    """A data a partir da qual o segundo fator é exigido, ou None (desligado)."""
    from datetime import date

    from django.conf import settings

    valor = (getattr(settings, 'SEGUNDO_FATOR_OBRIGATORIO_DESDE', '') or '').strip().lower()
    if not valor or valor == 'desligado':
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def segundo_fator_pendente(user, papeis):
    """Este vínculo precisa de segundo fator e o usuário ainda não tem?"""
    if prazo_do_segundo_fator() is None:
        return False
    if not (set(papeis or ()) & PAPEIS_COM_SEGUNDO_FATOR):
        return False
    return not user_has_confirmed_totp(user)


def segundo_fator_exigido_hoje():
    prazo = prazo_do_segundo_fator()
    return prazo is not None and timezone.localdate() >= prazo
