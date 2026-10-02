"""O e-mail da instalação sai pelo worker, não pelo processo web.

**Por que isto existe.** No Swarm o serviço `app` está em
`traefik_public` + `neurodoc_v1_internal`; quem tem saída para a internet
é o `celery_worker`, em `neurodoc_v1_egress` (`docker-stack.yml`). O
desenho sempre soube disso — o segredo `NEURODOC_SMTP_PASSWORD` só é
entregue ao worker, e `core/settings.py` só o exige quando
`SERVICE_ROLE == 'worker'` —, mas a verificação de e-mail e a recuperação
de senha chamavam `send_mail` **dentro da requisição**, no processo web.

Em desenvolvimento isso funciona, porque ali tudo alcança tudo. Em
produção, cada cadastro e cada "esqueci minha senha" travaria dez segundos
no `EMAIL_TIMEOUT` e falharia — no primeiro dia, para todo mundo.

A correção poderia ter sido uma tarefa em cada ponto de envio. Um backend
resolve os pontos que ainda não existem também: `PasswordResetForm` do
próprio Django, o e-mail de erro para `ADMINS`, e a próxima tela que
alguém escrever chamando `send_mail` sem saber de nada disto.

**Não cobre o SMTP da clínica.** `communications/email.py` monta uma
conexão explícita quando o médico ou a clínica tem servidor próprio, e
conexão explícita não passa por backend nenhum. Esses envios nascem de
eventos despachados por `events.tasks.dispatch_outbox`, que já roda no
worker — o que sobra são os disparos feitos direto de uma view, anotados
em `docs/homologation/email-delivery.md`.
"""
from django.core.mail.backends.base import BaseEmailBackend


class AttachmentNotSupported(Exception):
    """Anexo não atravessa a fila, e falhar é melhor do que sumir."""


def serialize(message):
    """A mensagem vira dados simples, para caber numa tarefa.

    Anexo é recusado de propósito, em vez de descartado em silêncio. Hoje
    nada anexa — a entrega de documento manda um **link** com token, e não
    o PDF —, e há duas razões para manter assim: um PDF de prontuário num
    corpo de mensagem do broker é dado de paciente atravessando mais um
    salto, e mensagem grande é a forma clássica de entupir a fila.

    Se algum dia precisar, o caminho é a tarefa buscar o anexo do disco
    pelo id, não carregá-lo daqui.
    """
    if getattr(message, 'attachments', None):
        raise AttachmentNotSupported(
            'Anexo não é enviado pela fila: mande um link com token, como faz '
            'a entrega de documento.'
        )
    return {
        'subject': message.subject,
        'body': message.body,
        'from_email': message.from_email,
        'to': list(message.to or []),
        'cc': list(message.cc or []),
        'bcc': list(message.bcc or []),
        'reply_to': list(message.reply_to or []),
        # `alternatives` é o HTML de um `EmailMultiAlternatives`. Vira lista
        # de listas porque JSON não tem tupla, e a tarefa desfaz.
        'alternatives': [list(item) for item in getattr(message, 'alternatives', None) or []],
    }


class WorkerEmailBackend(BaseEmailBackend):
    """Enfileira em vez de abrir conexão SMTP aqui.

    Devolve quantas mensagens foram aceitas para envio, que é o contrato de
    `BaseEmailBackend` — e é honesto: aceitas, não entregues. Nenhum backend
    do Django promete entrega; o SMTP também devolve na hora em que o
    servidor aceitou.
    """

    def send_messages(self, email_messages):
        """Enfileira cada mensagem **depois do commit**.

        Era `.delay()` direto, e isso produziu o defeito mais traiçoeiro
        desta área: o e-mail chegava e o link dentro dele não valia.

        O caminho era este. A entrega de documento roda numa transação que
        **cria o token** e manda o e-mail; `.delay()` dentro dela põe a
        tarefa na fila na hora, e o worker é mais rápido que o resto da
        requisição. Dois desfechos, os dois ruins: ou o worker manda o
        e-mail antes de o token estar visível para outra conexão, ou a
        transação falha depois do envio e o token **deixa de existir** —
        que foi o que aconteceu quando o SMS estourou. O paciente recebia
        um link para uma linha que nunca foi gravada, e a tela dizia
        "inválido ou expirado".

        `on_commit` amarra o envio ao sucesso da transação. Fora de
        transação ele executa na hora, então os pontos que já enviavam sem
        transação nenhuma não mudam de comportamento.

        Vale para **todo** e-mail do produto, e é por isso que a correção
        mora aqui e não em cada chamador: verificação de endereço, convite,
        recuperação de senha e descadastro criam um token do mesmo jeito, e
        cada um teria de lembrar sozinho.
        """
        from django.db import transaction

        from .tasks import deliver_installation_email

        aceitas = 0
        for message in email_messages or []:
            if not message.to and not message.cc and not message.bcc:
                continue
            try:
                dados = serialize(message)
            except AttachmentNotSupported:
                if self.fail_silently:
                    continue
                raise
            transaction.on_commit(
                lambda payload=dados: deliver_installation_email.delay(payload)
            )
            aceitas += 1
        return aceitas
