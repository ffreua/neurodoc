"""A agenda do dia seguinte, por e-mail, para cada médico (1.36).

Todo dia às `settings.AGENDA_POR_EMAIL_HORA` (19h de Brasília), cada médico com horário marcado
para amanhã recebe, no e-mail da própria conta, a lista do dia: horário,
paciente, tipo de consulta e se o paciente já confirmou. Uma mensagem por
médico **e por clínica** — quem atende em duas recebe duas, cada uma com o
nome da clínica no assunto, porque são duas agendas e duas recepções.

**Quem recebe.** Vínculo ativo com o papel médico, conta ativa, a opção
`Membership.agenda_por_email` ligada (padrão) e a clínica não encerrada. A
suspensa recebe: ela congela a escrita, não a agenda — os pacientes dela
continuam vindo. Dia sem horário não gera e-mail: "amanhã você não tem
ninguém" todo sábado é o tipo de mensagem que ensina a ignorar a próxima.

**Por onde sai.** `communications.email.send_email` com a clínica, e não
com o médico: o remetente é o servidor de e-mail da clínica, se ela
cadastrou, senão o da instalação — a cadeia de sempre (CLAUDE.md §7-G), só
que começando na clínica. O remetente pessoal do médico existe para falar
com os pacientes dele; aqui quem escreve é a clínica, para o médico.

**Uma vez por dia, mesmo com a tarefa rodando duas.** A linha de
`AgendaPorEmailEnvio` (médico, dia) é gravada antes do envio, com `UNIQUE`;
quem perde a corrida pela linha não envia.

**O que vai no e-mail é agenda, não prontuário**: o mesmo que a grade mostra
à secretária (nome, horário, tipo). Nada clínico — nem diagnóstico, nem
motivo. Vai ao e-mail **da conta do médico**, o mesmo que recebe a
recuperação de senha.

**O que fica de fora**: horário cancelado e falta. O que for marcado depois
do envio não entra — o e-mail diz a hora em que a lista foi tirada.
"""
import logging
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Hora do envio, em Brasília: `AGENDA_POR_EMAIL_HORA` em `core/settings.py`,
#: que também agenda a tarefa. No fim da tarde: a agenda de amanhã já está
#: quase fechada, e o médico ainda lê antes de dormir.


def amanha(agora=None):
    return timezone.localdate(agora or timezone.now()) + timedelta(days=1)


def _limites_do_dia(dia):
    fuso = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime.combine(dia, time.min), fuso)
    return inicio, inicio + timedelta(days=1)


def horarios_do_dia(membership, dia):
    """Os horários vivos do médico no dia, em ordem. Sem cancelado nem falta."""
    from .models import OCCUPYING_STATUSES, Appointment

    inicio, fim = _limites_do_dia(dia)
    return list(
        Appointment.objects.filter(
            tenant_id=membership.tenant_id, physician_membership=membership,
            starts_at__gte=inicio, starts_at__lt=fim, status__in=OCCUPYING_STATUSES,
        ).select_related('patient').order_by('starts_at')
    )


def situacao(appointment):
    """O que a coluna "confirmação" diz. Agendado e ainda não confirmado é
    o caso que interessa ao médico — é quem a recepção ainda vai ligar."""
    from .models import AppointmentStatus

    if appointment.status == AppointmentStatus.SCHEDULED:
        return 'A confirmar'
    if appointment.status == AppointmentStatus.CONFIRMED:
        return 'Confirmado'
    return appointment.get_status_display()


def destinatarios():
    """Os vínculos que recebem: médico ativo, opção ligada, clínica não encerrada."""
    from tenancy.models import Membership, MembershipStatus, Role, TenantStatus

    return (
        Membership.objects.filter(
            status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR], agenda_por_email=True,
            user__is_active=True,
        )
        .exclude(tenant__status=TenantStatus.CLOSED)
        .exclude(user__email='')
        .select_related('user', 'tenant')
    )


def contexto(membership, dia, horarios, agora=None):
    from base.seo import absoluta

    agora = agora or timezone.now()
    linhas = [{
        'inicio': timezone.localtime(a.starts_at),
        'fim': timezone.localtime(a.ends_at),
        'paciente': a.patient.full_name,
        'tipo': a.get_type_display(),
        'situacao': situacao(a),
        'confirmado': situacao(a) == 'Confirmado',
        'encaixe': a.is_overbook,
        'teleatendimento': a.teleatendimento,
    } for a in horarios]
    return {
        'medico': membership.user.get_full_name() or membership.user.email,
        'clinica': membership.tenant.trade_name or membership.tenant.legal_name,
        'dia': dia,
        'linhas': linhas,
        'total': len(linhas),
        'confirmados': sum(1 for linha in linhas if linha['confirmado']),
        'tirada_em': timezone.localtime(agora),
        'url_agenda': absoluta(reverse('scheduling:day')) + f'?date={dia.isoformat()}',
        # O vínculo vai na URL: quem atende em duas clínicas pode estar com a
        # outra aberta na sessão, e desligaria o e-mail da clínica errada.
        'url_desligar': absoluta(reverse('scheduling:agenda-por-email', args=[membership.id])),
    }


def assunto(membership, dia):
    clinica = membership.tenant.trade_name or membership.tenant.legal_name
    return f'Sua agenda de {dia:%d/%m} — {clinica}'


def enviar(membership, dia, agora=None):
    """Manda a agenda de `dia` a este médico. Devolve o que aconteceu.

    `'vazio'` (sem horário, nada enviado nem gravado), `'repetido'` (já
    havia linha para o médico e o dia), `'enviado'` ou `'falhou'`.
    """
    from communications.email import send_email

    from .models import AgendaPorEmailEnvio

    horarios = horarios_do_dia(membership, dia)
    if not horarios:
        return 'vazio'
    try:
        with transaction.atomic():
            registro = AgendaPorEmailEnvio.objects.create(
                tenant_id=membership.tenant_id, membership=membership, dia=dia, horarios=len(horarios),
            )
    except IntegrityError:
        return 'repetido'
    dados = contexto(membership, dia, horarios, agora)
    # O idioma ativado à força: no worker não há requisição, e sem ele o
    # `date:"l"` do modelo escreve "Thursday" no meio do e-mail em português.
    from django.conf import settings
    from django.utils import translation

    with translation.override(settings.LANGUAGE_CODE):
        texto = render_to_string('scheduling/email/agenda_do_dia.txt', dados)
        html = render_to_string('scheduling/email/agenda_do_dia.html', dados)
    try:
        send_email(
            membership.user.email, assunto(membership, dia), texto,
            tenant_id=membership.tenant_id, html_body=html,
        )
    except Exception as exc:                                # noqa: BLE001
        # A linha fica, com o erro: um e-mail de agenda repetido amanhã de
        # manhã, quando o defeito for corrigido, já não serviria para nada.
        logger.warning('agenda_por_email: falha ao enfileirar (tenant=%s)', membership.tenant_id, exc_info=True)
        AgendaPorEmailEnvio.objects.filter(id=registro.id).update(erro=f'{type(exc).__name__}'[:255])
        return 'falhou'
    AgendaPorEmailEnvio.objects.filter(id=registro.id).update(enviado_em=timezone.now())
    return 'enviado'


def rodada(agora=None):
    """A tarefa diária: a agenda de amanhã a cada médico que tem horário."""
    dia = amanha(agora)
    contagem = {'enviado': 0, 'vazio': 0, 'repetido': 0, 'falhou': 0}
    for membership in destinatarios():
        try:
            contagem[enviar(membership, dia, agora)] += 1
        except Exception:                                   # noqa: BLE001
            logger.exception('agenda_por_email: falha inesperada (tenant=%s)', membership.tenant_id)
            contagem['falhou'] += 1
    return contagem
