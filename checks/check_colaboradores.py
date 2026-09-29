"""Convite completo, confirmação de conta e administração de credenciais."""
import re
import uuid

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core import mail
from django.test import Client, override_settings

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
settings.SECURE_SSL_REDIRECT = False

from accounts.models import RecoveryCode, User
from django_otp.plugins.otp_totp.models import TOTPDevice
from tenancy.models import Invitation, Membership, MembershipStatus, Role, Tenant


falhas = []
tenant = Tenant.objects.get(slug="demo-clinica-a")
owner = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=[Role.OWNER],
).select_related("user").first()
if owner is None:
    print("PULADO: demonstração sem responsável ativo")
    raise SystemExit(0)

email = f"colaborador-{uuid.uuid4().hex[:10]}@example.com"
cliente = Client()
cliente.force_login(owner.user)
sessao = cliente.session
sessao["tenant_id"] = str(tenant.id)
sessao.save()

created_user = None
invitation = None

with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
    mail.get_connection()
    mail.outbox.clear()
    print("=== 1. convite mostra URL absoluta e envia automaticamente ===")
    resposta = cliente.post(
        "/app/org/equipe/",
        {"email": email, "roles": [Role.SECRETARY, Role.MANAGER]},
        secure=True,
    )
    corpo = resposta.content.decode("utf-8", "replace")
    invitation = Invitation.objects.filter(target_tenant=tenant, email_binding=email).latest("created_at")
    absoluto = re.search(r"https://testserver/invite/([^/]+)/", corpo)
    print("  URL absoluta=", bool(absoluto), "e-mails=", len(mail.outbox))
    if not absoluto:
        falhas.append("a tela do convite não mostra URL HTTPS absoluta")
        relativo = re.search(r"/invite/([^/]+)/", corpo)
        token = relativo.group(1) if relativo else "inexistente"
    else:
        token = absoluto.group(1)
    if not mail.outbox or mail.outbox[-1].to != [email]:
        falhas.append("criar o convite não envia automaticamente ao colaborador")

    print("=== 2. cadastro exige confirmação de senha ===")
    pagina = Client().get(f"/invite/{token}/")
    html = pagina.content.decode("utf-8", "replace")
    tem_dupla = 'name="password1"' in html and 'name="password2"' in html
    print("  dois campos=", tem_dupla)
    if not tem_dupla:
        falhas.append("o aceite do convite não pede confirmação da senha")

    divergente = Client().post(
        f"/invite/{token}/",
        {"email": email, "password1": "Senha-forte-123!", "password2": "Outra-senha-123!"},
    )
    invitation.refresh_from_db()
    if invitation.consumed_at is not None or divergente.status_code != 200:
        falhas.append("senhas divergentes consumiram o convite ou não voltaram ao formulário")

    print("=== 3. conta válida recebe confirmação de e-mail ===")
    mail.outbox.clear()
    resposta = Client().post(
        f"/invite/{token}/",
        {"email": email, "password1": "Senha-forte-123!", "password2": "Senha-forte-123!"},
    )
    created_user = User.objects.filter(email=email).first()
    recebeu = bool(mail.outbox and mail.outbox[-1].to == [email] and "/accounts/verify-email/" in mail.outbox[-1].body)
    print("  conta criada=", bool(created_user), "verificação enviada=", recebeu)
    if created_user is None:
        falhas.append("o formulário com duas senhas válidas não criou a conta")
    elif not recebeu:
        falhas.append("a conta criada por convite não recebeu o e-mail de confirmação")

    print("=== 4. reenvio não é capturado como token ===")
    if created_user is not None:
        reenviar = Client()
        reenviar.force_login(created_user)
        mail.outbox.clear()
        resposta = reenviar.post("/accounts/verify-email/resend/")
        print("  status=", resposta.status_code, "e-mails=", len(mail.outbox))
        if resposta.status_code == 405 or not mail.outbox:
            falhas.append("o reenvio de confirmação ainda retorna 405 ou não envia")

    print("=== 5. responsável pode enviar senha e resetar MFA com código ===")
    if created_user is not None:
        membership = Membership.objects.get(tenant=tenant, user=created_user)
        target_device = TOTPDevice.objects.create(user=created_user, name="roteiro-alvo", confirmed=True)
        RecoveryCode.objects.create(user=created_user, code_hash="nao-utilizado")
        owner_device = TOTPDevice.objects.filter(user=owner.user, confirmed=True).first()
        if owner_device is None:
            owner_device = TOTPDevice.objects.create(user=owner.user, name="roteiro-owner", confirmed=True)
        owner_recovery_raw = f"recovery-{uuid.uuid4().hex}"
        owner_recovery = RecoveryCode.objects.create(
            user=owner.user, code_hash=make_password(owner_recovery_raw),
        )

        mail.outbox.clear()
        senha = cliente.post(f"/app/org/equipe/{membership.id}/redefinir-senha/")
        enviou_senha = bool(mail.outbox and mail.outbox[-1].to == [email])
        print("  senha status=", senha.status_code, "e-mail=", enviou_senha)
        if senha.status_code not in (302, 303) or not enviou_senha:
            falhas.append("a ação do responsável não enviou redefinição de senha")

        sem_codigo = cliente.post(f"/app/org/equipe/{membership.id}/resetar-mfa/", {"code": "000000"})
        target_device.refresh_from_db()
        if not target_device.confirmed:
            falhas.append("um código MFA inválido resetou o colaborador")
        com_codigo = cliente.post(
            f"/app/org/equipe/{membership.id}/resetar-mfa/",
            {"code": owner_recovery_raw},
        )
        ainda_tem = TOTPDevice.objects.filter(user=created_user, confirmed=True).exists()
        ainda_codigos = RecoveryCode.objects.filter(user=created_user, used_at=None).exists()
        print("  MFA status=", com_codigo.status_code, "dispositivo=", ainda_tem, "recuperação=", ainda_codigos)
        if com_codigo.status_code not in (302, 303) or ainda_tem or ainda_codigos:
            falhas.append("o reset de MFA autenticado não removeu dispositivos e códigos")
        RecoveryCode.objects.filter(id=owner_recovery.id).delete()

        print("=== 6. vínculo inativo não autoriza mexer na conta global ===")
        membership.status = MembershipStatus.SUSPENDED
        membership.save(update_fields=["status", "updated_at"])
        protected_device = TOTPDevice.objects.create(
            user=created_user, name="roteiro-inativo", confirmed=True,
        )
        second_recovery_raw = f"recovery-{uuid.uuid4().hex}"
        second_recovery = RecoveryCode.objects.create(
            user=owner.user, code_hash=make_password(second_recovery_raw),
        )
        mail.outbox.clear()
        blocked_password = cliente.post(f"/app/org/equipe/{membership.id}/redefinir-senha/")
        blocked_mfa = cliente.post(
            f"/app/org/equipe/{membership.id}/resetar-mfa/", {"code": second_recovery_raw},
        )
        protected_device.refresh_from_db()
        print(
            "  senha=", blocked_password.status_code, "MFA=", blocked_mfa.status_code,
            "dispositivo preservado=", protected_device.confirmed,
        )
        if (
            blocked_password.status_code != 404
            or blocked_mfa.status_code != 404
            or mail.outbox
            or not protected_device.confirmed
        ):
            falhas.append("vínculo inativo ainda conseguiu alterar credenciais globais")
        RecoveryCode.objects.filter(id=second_recovery.id).delete()

if created_user is not None:
    Membership.objects.filter(user=created_user, tenant=tenant).delete()
    TOTPDevice.objects.filter(user=created_user).delete()
    RecoveryCode.objects.filter(user=created_user).delete()
    User.objects.filter(id=created_user.id).delete()
if invitation is not None:
    Invitation.objects.filter(id=invitation.id).delete()

print("---")
if falhas:
    for falha in falhas:
        print("FALHA:", falha)
    raise SystemExit(1)
print("OK: convite, confirmação, senha e MFA têm fluxo completo e seguro.")
