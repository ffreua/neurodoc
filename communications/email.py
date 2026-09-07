from django.conf import settings
from django.core.mail import EmailMessage, get_connection


class EmailSendFailed(Exception):
    pass


def _sender_settings(physician_membership):
    """Configuração de e-mail do médico, se ativa."""
    if physician_membership is None:
        return None
    row = getattr(physician_membership, 'email_settings', None)
    if row is None or not row.enabled or not row.from_email:
        return None
    return row


def _connection_for(sender):
    """Conexão SMTP do médico, ou None para usar a da instalação.

    Servidor próprio é opcional: um médico pode querer apenas que o e-mail
    saia no nome dele, pelo servidor da clínica. Só quando há host
    configurado é que se abre uma conexão separada.
    """
    if sender is None or not sender.uses_own_server:
        return None
    from base.crypto import SecretUnavailable

    try:
        password = sender.smtp_password()
    except SecretUnavailable as exc:
        raise EmailSendFailed(str(exc)) from exc
    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=sender.smtp_host, port=sender.smtp_port,
        username=sender.smtp_user or None, password=password or None,
        use_tls=sender.use_tls, use_ssl=sender.use_ssl, fail_silently=False,
    )


def send_email(to_email, subject, body_text, physician_membership=None):
    """Envia e-mail pelo framework nativo do Django.

    O remetente é o do médico quando ele tem configuração ativa, e o da
    instalação nos outros casos — é por isso que o parâmetro é o vínculo, e
    não um endereço: quem decide o remetente é a configuração, não quem
    chama.

    Em desenvolvimento o backend é o `locmem` (EMAIL_ENABLED=False, ver
    `core/settings.py`), e o envio continua sendo exercitável sem servidor.
    """
    sender = _sender_settings(physician_membership)
    from_email = sender.sender_header() if sender else settings.DEFAULT_FROM_EMAIL
    reply_to = [sender.reply_to] if sender and sender.reply_to else None

    message = EmailMessage(
        subject=subject, body=body_text, from_email=from_email, to=[to_email],
        reply_to=reply_to,
    )
    try:
        connection = _connection_for(sender)
    except EmailSendFailed:
        raise
    if connection is not None:
        message.connection = connection
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        raise EmailSendFailed(str(exc)) from exc


def verify_sender(sender):
    """Abre a conexão SMTP do médico só para ver se ela funciona.

    É o botão "testar" da tela: confirma host, porta, usuário e senha sem
    mandar e-mail para o endereço de ninguém.
    """
    if not sender.uses_own_server:
        raise EmailSendFailed(
            'Sem servidor SMTP próprio para testar. O envio usará o servidor da instalação.'
        )
    connection = _connection_for(sender)
    try:
        connection.open()
    except Exception as exc:
        raise EmailSendFailed(f'{exc.__class__.__name__}: {exc}') from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return True
