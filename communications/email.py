from django.conf import settings
from django.core.mail import EmailMessage


class EmailSendFailed(Exception):
    pass


def send_email(to_email, subject, body_text):
    """Uses Django's native mail framework -- the SMTP backend in
    production (SMTP_PASSWORD required, P-03), locmem in dev/tests when
    EMAIL_ENABLED is False (see core/settings.py). No separate transport
    layer of our own: this is exactly "backend nativo de e-mail Django".
    """
    message = EmailMessage(subject=subject, body=body_text, from_email=settings.DEFAULT_FROM_EMAIL, to=[to_email])
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        raise EmailSendFailed(str(exc)) from exc
