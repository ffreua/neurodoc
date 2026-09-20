"""Mensagens da clínica para quem mantém a instalação.

O caminho inverso de `tenancy/leads.py`: lá é alguém de fora pedindo para
entrar, aqui é uma clínica que já usa o sistema pedindo ajuda ou sugerindo
uma mudança. Os dois terminam no mesmo console, e por isso compartilham a
mesma disciplina — grava primeiro, avisa depois, e falha de aviso não
perde a mensagem.

**Limite por autor, e não por IP.** O formulário do site é público e
anônimo, então lá o IP é o que existe para contar. Aqui quem escreve está
autenticado e com vínculo ativo: contar por vínculo é contar por pessoa, e
uma clínica inteira atrás do mesmo IP não fica sem voz porque um colega
escreveu três vezes.
"""

from django.conf import settings
from django.utils import timezone

from .models import ClinicMessage, ClinicMessageKind, ClinicMessageStatus

#: Mensagens por vínculo na janela. Quatro numa hora cobre quem escreve,
#: percebe que esqueceu um detalhe e escreve de novo; acima disso não é
#: mais alguém tentando ser entendido.
RATE_LIMIT = 4
RATE_WINDOW_SECONDS = 3600


def rate_limited(membership_id):
    """Conta mensagens por vínculo. Falha **aberta** se a cache estiver fora.

    A mesma escolha do formulário de contato, pela mesma razão: o pior
    caso aqui é uma mensagem repetida no console, e fechar transformaria
    uma indisponibilidade do Redis em clínica que não consegue pedir
    ajuda — exatamente quando algo pode estar errado no sistema.
    """
    from django.core.cache import cache

    chave = f'clinic-message:{membership_id}'
    try:
        cache.get_or_set(chave, 0, RATE_WINDOW_SECONDS)
        return cache.incr(chave) > RATE_LIMIT
    except Exception:                                   # noqa: BLE001
        return False


def _resumo(mensagem):
    """O corpo do aviso. Texto simples, e só o que foi digitado.

    Sem nada do prontuário, e sem nome de paciente: quem recebe este
    e-mail opera o servidor e não tem — nem deve ganhar aqui — acesso a
    conteúdo clínico.
    """
    autor = mensagem.author
    clinica = mensagem.tenant
    return '\n'.join([
        f'{mensagem.get_kind_display()} — NeuroDoc',
        '',
        f'Clínica:  {clinica.trade_name or clinica.legal_name}',
        f'Autor:    {autor.user.get_full_name() or autor.user.email} <{autor.user.email}>',
        f'Papéis:   {", ".join(autor.roles)}',
        f'Assunto:  {mensagem.subject}',
        '',
        mensagem.body,
        '',
        '--',
        f'Mensagem {mensagem.id} · responda ao e-mail do autor.',
    ])


def notify(mensagem):
    """Avisa quem opera a instalação. Falha aqui não perde a mensagem.

    Destino é `LEADS_EMAIL`, o mesmo endereço que recebe pedido de
    contato: é a caixa de quem cuida do produto. Um segundo endereço de
    configuração só para isto seria mais uma variável de ambiente para
    alguém esquecer de preencher — e uma mensagem de suporte que não chega
    a lugar nenhum.
    """
    from communications.email import send_email

    try:
        send_email(
            settings.LEADS_EMAIL,
            f'[NeuroDoc] {mensagem.get_kind_display()}: {mensagem.subject}',
            _resumo(mensagem),
        )
    except Exception as exc:                            # noqa: BLE001
        # Truncado e guardado, como no lead: o corpo do erro pode trazer
        # endereço de servidor e usuário de SMTP.
        ClinicMessage.objects.filter(id=mensagem.id).update(
            notify_error=str(exc)[:255],
        )
        return False
    ClinicMessage.objects.filter(id=mensagem.id).update(
        notified_at=timezone.now(), notify_error='',
    )
    return True


def create(context, membership, kind, subject, body):
    """Grava a mensagem e tenta avisar.

    `kind` chega da URL e é conferido contra as opções: um valor
    desconhecido vira suporte, que é o lado seguro — melhor uma sugestão
    lida como pedido de ajuda do que um pedido de ajuda perdido numa
    gaveta de ideias.
    """
    from audit.services import record_audit_event

    if kind not in ClinicMessageKind.values:
        kind = ClinicMessageKind.SUPPORT

    mensagem = ClinicMessage.objects.create(
        tenant_id=context.tenant_id,
        author=membership,
        kind=kind,
        subject=subject.strip()[:140],
        body=body.strip()[:4000],
        status=ClinicMessageStatus.NEW,
    )
    # A trilha registra que houve mensagem, o tipo e o autor -- nunca o
    # texto. Auditoria é saber quem fez o quê, não guardar uma segunda
    # cópia do que foi escrito.
    record_audit_event(
        context.user_id, context.tenant_id, 'tenancy.clinic_message_sent',
        object_type='clinic_message', object_id=mensagem.id, outcome='success',
        integrity_metadata={'kind': kind},
    )
    notify(mensagem)
    return mensagem
