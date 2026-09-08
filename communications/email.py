from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection


class EmailSendFailed(Exception):
    pass


def _doctor_settings(physician_membership):
    """Configuração de e-mail do médico, se ativa."""
    if physician_membership is None:
        return None
    row = getattr(physician_membership, 'email_settings', None)
    if row is None or not row.enabled or not row.from_email:
        return None
    return row


def _clinic_settings(tenant_id):
    """Configuração de e-mail da clínica, se ativa."""
    if tenant_id is None:
        return None
    from .models import MessagingSettings

    row = MessagingSettings.objects.filter(tenant_id=tenant_id).first()
    if row is None or not row.email_enabled or not row.email_from_address:
        return None
    return row


class _Sender:
    """Remetente resolvido, num formato só.

    Os dois modelos guardam a mesma coisa com nomes diferentes
    (`from_email` num, `email_from_address` no outro), porque nasceram em
    momentos diferentes. Traduzir aqui, num lugar, evita que cada função de
    envio precise saber de qual dos dois veio o que está mandando.
    """

    def __init__(self, header, reply_to, host, port, user, password_getter,
                 use_tls, use_ssl):
        self.header = header
        self.reply_to = reply_to
        self.host = host
        self.port = port
        self.user = user
        self._password_getter = password_getter
        self.use_tls = use_tls
        self.use_ssl = use_ssl

    @property
    def uses_own_server(self):
        return bool(self.host)

    def password(self):
        return self._password_getter()


def resolve_sender(physician_membership=None, tenant_id=None):
    """Quem assina o e-mail: o médico, senão a clínica, senão a instalação.

    A ordem responde a como um consultório funciona. O médico que configurou
    remetente próprio quer que o paciente dele receba no nome dele — é a
    escolha mais específica e ganha. Sem ela, o e-mail sai pela conta da
    clínica, que é o caso comum. Sem nenhuma das duas, sai pelo remetente da
    instalação, o que mantém funcionando quem já estava montado por variável
    de ambiente.
    """
    doctor = _doctor_settings(physician_membership)
    if doctor is not None:
        return _Sender(
            header=doctor.sender_header(), reply_to=doctor.reply_to,
            host=doctor.smtp_host, port=doctor.smtp_port, user=doctor.smtp_user,
            password_getter=doctor.smtp_password,
            use_tls=doctor.use_tls, use_ssl=doctor.use_ssl,
        )
    if physician_membership is not None and tenant_id is None:
        tenant_id = physician_membership.tenant_id
    clinic = _clinic_settings(tenant_id)
    if clinic is not None:
        return _Sender(
            header=clinic.sender_header(), reply_to=clinic.email_reply_to,
            host=clinic.smtp_host, port=clinic.smtp_port, user=clinic.smtp_user,
            password_getter=clinic.smtp_password,
            use_tls=clinic.smtp_use_tls, use_ssl=clinic.smtp_use_ssl,
        )
    return None


def _connection_for(sender):
    """Conexão SMTP própria, ou None para usar a da instalação.

    Servidor próprio é opcional em qualquer um dos níveis: um médico — ou
    uma clínica — pode querer só que o e-mail saia no nome dele, usando o
    servidor da instalação. Só quando há host configurado é que se abre uma
    conexão separada.
    """
    if sender is None or not sender.uses_own_server:
        return None
    from base.crypto import SecretUnavailable

    try:
        password = sender.password()
    except SecretUnavailable as exc:
        raise EmailSendFailed(str(exc)) from exc
    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=sender.host, port=sender.port,
        username=sender.user or None, password=password or None,
        use_tls=sender.use_tls, use_ssl=sender.use_ssl, fail_silently=False,
    )


def send_email(to_email, subject, body_text, physician_membership=None, tenant_id=None,
               html_body=None):
    """Envia e-mail pelo framework nativo do Django.

    O remetente sai de `resolve_sender` — médico, senão clínica, senão
    instalação. É por isso que o parâmetro é o vínculo, e não um endereço:
    quem decide o remetente é a configuração, não quem chama.

    Em desenvolvimento o backend é o `locmem` (EMAIL_ENABLED=False, ver
    `core/settings.py`), e o envio continua sendo exercitável sem servidor.
    """
    sender = resolve_sender(physician_membership, tenant_id)
    from_email = sender.header if sender else settings.DEFAULT_FROM_EMAIL
    reply_to = [sender.reply_to] if sender and sender.reply_to else None

    if html_body:
        # O texto simples continua sendo o corpo principal e o HTML é a
        # alternativa: cliente que não renderiza HTML, e filtro que o
        # descarta, ainda entregam a mensagem legível.
        message = EmailMultiAlternatives(
            subject=subject, body=body_text, from_email=from_email, to=[to_email],
            reply_to=reply_to,
        )
        message.attach_alternative(html_body, 'text/html')
    else:
        message = EmailMessage(
            subject=subject, body=body_text, from_email=from_email, to=[to_email],
            reply_to=reply_to,
        )

    connection = _connection_for(sender)
    if connection is not None:
        message.connection = connection
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        raise EmailSendFailed(str(exc)) from exc


def verify_connection(sender):
    """Abre a conexão SMTP só para ver se ela funciona.

    É o botão "testar" da tela: confirma host, porta, usuário e senha sem
    mandar e-mail para o endereço de ninguém.
    """
    if sender is None or not sender.uses_own_server:
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


def verify_sender(doctor_settings):
    """Testa a conexão de um `DoctorEmailSettings`.

    Continua existindo com este nome porque é o que a tela de mensageria já
    chama para o botão de teste por médico.
    """
    return verify_connection(_Sender(
        header=doctor_settings.sender_header(), reply_to=doctor_settings.reply_to,
        host=doctor_settings.smtp_host, port=doctor_settings.smtp_port,
        user=doctor_settings.smtp_user, password_getter=doctor_settings.smtp_password,
        use_tls=doctor_settings.use_tls, use_ssl=doctor_settings.use_ssl,
    ))


def send_test_email(to_email, physician_membership=None, tenant_id=None, label=''):
    """Manda um e-mail de teste de verdade, para um endereço informado.

    Abrir a conexão prova que o servidor aceita a senha; não prova que a
    mensagem chega. Remetente recusado por SPF, domínio sem DKIM e caixa que
    manda tudo para spam só aparecem num envio real — e é exatamente aí que
    o paciente deixa de receber a receita.

    O destinatário é digitado por quem testa, e o assunto diz que é teste:
    ninguém deve descobrir a configuração errada por um paciente reclamando.
    """
    origem = label or 'da clínica'
    return send_email(
        to_email,
        'NeuroDoc — teste de envio de e-mail',
        'Este é um e-mail de teste enviado pela tela de configuração do NeuroDoc.\n\n'
        f'Se você o recebeu, o servidor de e-mail {origem} está funcionando e as '
        'mensagens do sistema — confirmação de horário e entrega de documento — '
        'sairão por ele.\n\n'
        'Nenhum dado de paciente foi usado neste teste.\n',
        physician_membership=physician_membership, tenant_id=tenant_id,
    )
