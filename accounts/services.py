from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from audit.services import record_audit_event
from tenancy.context import active_membership_for
from tenancy.models import MembershipStatus

EMAIL_VERIFICATION_SALT = 'accounts.email-verification'
EMAIL_VERIFICATION_MAX_AGE = 60 * 60 * 24


def generate_email_verification_token(user):
    return signing.dumps({'user_id': str(user.id)}, salt=EMAIL_VERIFICATION_SALT)


def read_email_verification_token(token):
    try:
        data = signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=EMAIL_VERIFICATION_MAX_AGE)
    except signing.BadSignature:
        return None
    return data.get('user_id')


def send_email_verification(user, request):
    token = generate_email_verification_token(user)
    path = f'/accounts/verify-email/{token}/'
    url = request.build_absolute_uri(path)
    send_mail(
        subject='Confirme seu e-mail — NeuroDoc',
        message=render_to_string('accounts/email/verify_email.txt', {'url': url}),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


@transaction.atomic
def confirm_email_verification(token):
    user_id = read_email_verification_token(token)
    if not user_id:
        return None
    from .models import User
    user = User.objects.select_for_update().filter(id=user_id, is_active=True).first()
    if user is None:
        return None
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at'])
    return user


@transaction.atomic
def switch_tenant(request, tenant_id):
    membership = active_membership_for(request.user, tenant_id)
    if membership is None:
        return False
    request.session['tenant_id'] = str(membership.tenant_id)
    record_audit_event(
        request.user, membership.tenant, 'tenancy.tenant_switched',
        object_type='membership', object_id=membership.id, outcome='success',
    )
    return True


@transaction.atomic
def revoke_membership(membership, actor):
    membership.status = MembershipStatus.REVOKED
    membership.revoked_at = timezone.now()
    membership.row_version += 1
    membership.save(update_fields=['status', 'revoked_at', 'row_version', 'updated_at'])
    record_audit_event(
        actor, membership.tenant, 'tenancy.membership_revoked',
        object_type='membership', object_id=membership.id, outcome='success',
    )
    return membership
