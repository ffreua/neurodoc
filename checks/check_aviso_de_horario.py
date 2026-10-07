"""O paciente é avisado quando o horário dele muda de estado.

Antes desta entrega, **marcar e cancelar nao avisavam ninguem**. Havia o
lembrete automatico (24h e 2h antes) e a confirmacao que a secretaria
manda a mao -- e mais nada. Quem tivesse a consulta cancelada descobria
ao chegar na clinica, ou ao nao receber o lembrete que esperava.

E o que a confirmacao mandava dizia `Local .......... <nome da clinica>`,
que o paciente ja sabe e que nao o leva a lugar nenhum. O endereco
existia no codigo, num bloco separado, e ficava vazio quando a clinica
nao tinha preenchido a identidade -- que era o caso da segunda clinica
real.

Este roteiro cobre as duas coisas: que o aviso sai, e que ele diz onde é.
"""
import re
from pathlib import Path

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from communications.models import Delivery, DeliveryChannel
from communications.services import ASSUNTOS, _confirmation_message
from scheduling.models import Appointment
from tenancy.models import ClinicProfile, Tenant

failures = []
raiz = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    print(f'  {"ok  " if condicao else "FALHA"}  {descricao}'
          + (f'  [{detalhe}]' if detalhe and not condicao else ''))
    if not condicao:
        failures.append(descricao)


consulta = Appointment.objects.select_related(
    'tenant', 'patient', 'physician_membership__user',
).first()
if consulta is None:
    print('FALTA DADO: nenhum agendamento no banco; o roteiro nao pode afirmar nada')
    raise SystemExit(1)

perfil = ClinicProfile.objects.filter(tenant_id=consulta.tenant_id).first()
guardado = None
if perfil is not None:
    guardado = (perfil.address_line, perfil.address_district, perfil.city,
                perfil.state, perfil.postal_code, perfil.phone)

ENDERECO = 'Rua Cubatao, 86 - Cj 409'
FONE = '(11) 3287-3247'


def com_identidade(preenchida):
    """Poe a identidade da clinica em um dos dois estados possiveis."""
    if perfil is None:
        return
    if preenchida:
        perfil.address_line, perfil.address_district = ENDERECO, 'Vila Mariana'
        perfil.city, perfil.state, perfil.postal_code = 'Sao Paulo', 'SP', '04013000'
        perfil.phone = FONE
    else:
        perfil.address_line = perfil.address_district = perfil.city = ''
        perfil.state = perfil.postal_code = perfil.phone = ''
    perfil.save()


try:
    print('=== 1. o Local e o endereco, e nao so o nome da clinica ===')
    com_identidade(True)
    corpo = _confirmation_message(consulta, DeliveryChannel.EMAIL, motivo='booked')
    print('\n'.join('    ' + l for l in corpo.splitlines()[:10]))
    confere(ENDERECO in corpo, 'o endereco aparece no corpo')
    # A linha do Local tem de ser seguida pelo endereco, e nao por uma
    # linha em branco: o que o paciente procura e "onde", e o nome da
    # clinica sozinho nao responde.
    bloco = corpo.split('Local ..........', 1)[1]
    confere(ENDERECO in bloco.split('Telefone')[0],
            'o endereco vem colado no Local, nao num bloco solto')
    confere(FONE in corpo, 'o telefone da clinica aparece')
    confere('Telefone .......' in corpo, 'com rotulo proprio')
    confere('maps' in corpo, 'e o link do mapa')
    confere('04013-000' in corpo, 'o CEP sai com mascara', corpo)

    print('=== 2. o que a mensagem tem de dizer, nos tres casos ===')
    for motivo, esperado in (
        ('booked', 'marcada'), ('rescheduled', 'remarcada'), ('cancelled', 'CANCELADA'),
    ):
        corpo = _confirmation_message(consulta, DeliveryChannel.EMAIL, motivo=motivo)
        confere(esperado in corpo, f'{motivo}: a abertura diz "{esperado}"')
        # Data, profissional e local em TODOS -- inclusive no
        # cancelamento. Sem isso, quem tem duas consultas marcadas nao
        # sabe qual caiu.
        confere('Data e hora' in corpo and 'Profissional' in corpo and 'Local' in corpo,
                f'{motivo}: diz quando, com quem e onde')
        confere('ligue para a clínica' in corpo,
                f'{motivo}: manda ligar para ajustar')
        confere('não recebe respostas' in corpo,
                f'{motivo}: mantem o aviso de que a caixa nao responde')
        confere('não contém informação clínica' in corpo,
                f'{motivo}: diz que nao leva conteudo clinico')
    confere(set(ASSUNTOS) == {'booked', 'rescheduled', 'cancelled'},
            'ha um assunto proprio para cada caso', str(sorted(ASSUNTOS)))
    confere(len(set(ASSUNTOS.values())) == 3,
            'e os tres assuntos sao distintos -- "Consulta marcada" num '
            'cancelamento seria pior do que nenhum assunto')

    print('=== 3. sem endereco cadastrado, a mensagem diz isso ===')
    # O caso real da segunda clinica: identidade em branco. O texto nao
    # pode sugerir que o nome basta para chegar.
    com_identidade(False)
    corpo = _confirmation_message(consulta, DeliveryChannel.EMAIL, motivo='booked')
    confere('não cadastrado' in corpo or 'nao cadastrado' in corpo,
            'a falta do endereco e declarada, nao escondida',
            corpo.split('Local')[1][:80])
    confere('Telefone .......' not in corpo,
            'e sem telefone cadastrado nao sobra rotulo vazio')
finally:
    if perfil is not None and guardado is not None:
        (perfil.address_line, perfil.address_district, perfil.city,
         perfil.state, perfil.postal_code, perfil.phone) = guardado
        perfil.save()

print('=== 4. marcar, remarcar e cancelar emitem evento ===')
from scheduling import events as sched_events

for nome in ('RESERVED_TOPIC', 'RESCHEDULED_TOPIC', 'CANCELLED_TOPIC'):
    confere(hasattr(sched_events, nome), f'{nome} existe')

fonte = Path(raiz, 'scheduling', 'services.py').read_text(encoding='utf-8')
bloco = fonte.split('def cancel_appointment(')[1].split('\ndef ')[0]
confere('emit_appointment_cancelled(' in bloco,
        'cancelar emite o evento do cancelamento')
bloco = fonte.split('def reschedule_appointment(')[1].split('\n@')[0]
confere('emit_appointment_rescheduled(' in bloco,
        'remarcar emite o evento do remarcado')
bloco = fonte.split('def reserve_appointment(')[1].split('\n@')[0]
confere('emit_appointment_reserved(' in bloco,
        'marcar continua emitindo o que ja emitia')

print('=== 5. e ha quem consuma os tres ===')
from events.dispatcher import _HANDLERS  # noqa: F401  (mapa de consumidores)

# `_HANDLERS` mapeia prefixo -> [(nome do consumidor, funcao)].
registrados = {
    (topico, nome)
    for topico, entradas in _HANDLERS.items()
    for nome, _funcao in entradas
}
for topico, consumidor in (
    (sched_events.RESERVED_TOPIC, 'communications.appointment_booked'),
    (sched_events.RESCHEDULED_TOPIC, 'communications.appointment_rescheduled'),
    (sched_events.CANCELLED_TOPIC, 'communications.appointment_cancelled'),
):
    confere((topico, consumidor) in registrados, f'{consumidor} esta registrado',
            str(sorted(c for t, c in registrados if t == topico)))

# O CRM continua consumindo o `reserved`: o aviso ao paciente entrou como
# SEGUNDO consumidor do mesmo topico, e nao no lugar do primeiro.
do_reserved = {c for t, c in registrados if t == sched_events.RESERVED_TOPIC}
confere(len(do_reserved) >= 1,
        'o topico do agendamento aceita mais de um consumidor', str(do_reserved))

print('=== 6. o aviso sai por e-mail, e so uma vez ===')
from communications.services import deliver_appointment_notice
from patients.models import PatientContact

# **Volume antes de olhar.** Sem um contato com e-mail, a entrega nao
# acontece, as assercoes de idempotencia passam sobre lista vazia e o
# roteiro nao testa nada -- que e a armadilha que `check_paginacao` ja
# tinha ensinado neste repositorio.
contato, _ = PatientContact.objects.get_or_create(
    tenant_id=consulta.tenant_id, patient=consulta.patient,
    email='aviso-de-horario@roteiro.local',
    defaults={'name': 'Contato do roteiro', 'email_enabled': True},
)
confere(bool(consulta.patient.contacts.filter(email__gt='').exists()),
        'ha contato com e-mail para o aviso alcancar')


def _limpar_avisos():
    """Tira os avisos que uma passagem anterior deixou.

    Na ordem das chaves estrangeiras: `DeliveryAttempt` protege
    `Delivery`, que protege `PatientContact`.

    Antes **e** depois, de proposito. So depois nao basta: a limpeza
    pode falhar, e a passagem seguinte encontraria as entregas ja
    criadas, veria `get_or_create` devolver as existentes e concluiria
    que a idempotencia funciona sem ter criado nada. Foi exatamente o
    que aconteceu ao escrever este roteiro.
    """
    from communications.models import DeliveryAttempt

    entregas = Delivery.objects.filter(
        appointment=consulta, idempotency_key__startswith='notice:',
    )
    DeliveryAttempt.objects.filter(delivery__in=entregas).delete()
    entregas.delete()


_limpar_avisos()
antes = Delivery.objects.filter(appointment=consulta).count()
# `booked`, e nao `cancelled`: o agendamento usado aqui esta de pe, e
# a guarda de coerencia (ver `deliver_appointment_notice`) recusa
# avisar cancelamento de quem nao foi cancelado. Medir idempotencia
# com um motivo que o produto recusa mede o nada.
primeira = deliver_appointment_notice(consulta, 'booked', consulta.row_version)
segunda = deliver_appointment_notice(consulta, 'booked', consulta.row_version)
criadas = Delivery.objects.filter(appointment=consulta).count() - antes
print(f'  entregas criadas: {criadas} (duas chamadas do mesmo evento)')
confere(len(primeira) >= 1,
        'o aviso gerou entrega de verdade -- sem isto o resto desta secao '
        'passaria sobre lista vazia', f'{len(primeira)} entregas')
confere(len(primeira) == len(segunda),
        'a reentrega do evento devolve as mesmas entregas')
confere(criadas == len(primeira),
        'e nao cria entrega nova -- o paciente nao recebe dois e-mails do '
        'mesmo aviso', f'{criadas} criadas para {len(primeira)} contatos')
confere(all(d.channel == DeliveryChannel.EMAIL for d in primeira),
        'o aviso automatico e so por e-mail -- SMS custa credito e segue '
        'sendo ato de quem atende')

# Versao diferente do agendamento e aviso diferente: cancelar depois de
# remarcar sao dois fatos, e o paciente precisa dos dois.
terceira = deliver_appointment_notice(consulta, 'booked', consulta.row_version + 1)
confere(all(d.id not in {x.id for x in primeira} for d in terceira),
        'versao nova do agendamento gera aviso novo')
_limpar_avisos()
# O contato continua vivo ate o fim do roteiro: as secoes seguintes
# tambem precisam de alguem para quem escrever, e apaga-lo aqui as fazia
# medir lista vazia.

print('=== 6b. evento velho NAO vira aviso ===')
# O acidente de 07/10/2026, e o mais caro desta serie.
#
# `appointment_reserved` era emitido desde sempre e **ninguem o
# consumia** -- e o dispatcher deixa evento sem consumidor PENDENTE de
# proposito, para que "um deploy futuro possa registrar". Isso esta
# certo para integracao de dados: um CRM que chega depois quer o
# historico.
#
# Esta errado para mensagem a uma pessoa. Quando o consumidor do aviso
# entrou no ar as 01h12, encontrou 48 eventos pendentes e processou
# todos: dez e-mails sairam as 01h15 dizendo "sua consulta esta
# marcada". Quatro foram para pacientes de verdade -- dois sobre
# consultas que ja tinham acontecido, dois sobre consultas canceladas.
from communications.handlers import JANELA_DO_AVISO, _aviso
from datetime import timedelta as _td


class _EventoFalso:
    topic = 'scheduling.appointment_reserved'
    event_version = 1

    def __init__(self, idade, appointment_id):
        self.available_at = timezone.now() - idade
        self.created_at = self.available_at
        self.payload_minimal = {'appointment_id': str(appointment_id)}


confere(JANELA_DO_AVISO <= _td(hours=12),
        'a janela do aviso e curta o bastante para barrar replay',
        str(JANELA_DO_AVISO))
confere(JANELA_DO_AVISO >= _td(hours=1),
        'e generosa o bastante para o worker poder ficar fora do ar',
        str(JANELA_DO_AVISO))

# Um agendamento futuro e valido, para o teste medir a janela e nao
# outra guarda.
from scheduling.models import Appointment as _Ap, AppointmentStatus as _St

futuro = _Ap.objects.create(
    tenant=consulta.tenant, patient=consulta.patient,
    physician_membership=consulta.physician_membership,
    starts_at=timezone.now() + _td(days=3),
    ends_at=timezone.now() + _td(days=3, minutes=40),
    occupied_range=(timezone.now() + _td(days=3), timezone.now() + _td(days=3, minutes=40)),
    status=_St.SCHEDULED, type=consulta.type,
)
try:
    antes = Delivery.objects.filter(appointment=futuro).count()
    _aviso(_EventoFalso(_td(days=4), futuro.id), 'booked')
    confere(Delivery.objects.filter(appointment=futuro).count() == antes,
            'evento de quatro dias atras nao gera aviso nenhum')

    _aviso(_EventoFalso(_td(minutes=2), futuro.id), 'booked')
    confere(Delivery.objects.filter(appointment=futuro).count() > antes,
            'e o evento recente gera -- senao esta secao estaria medindo o nada')

    print('=== 6c. o estado de agora manda sobre o fato de entao ===')
    from communications.services import deliver_appointment_notice as _entregar

    # Consulta que ja aconteceu nunca vira "sua consulta esta marcada".
    passada = _Ap.objects.create(
        tenant=consulta.tenant, patient=consulta.patient,
        physician_membership=consulta.physician_membership,
        starts_at=timezone.now() - _td(days=2),
        ends_at=timezone.now() - _td(days=2) + _td(minutes=40),
        occupied_range=(timezone.now() - _td(days=2),
                        timezone.now() - _td(days=2) + _td(minutes=40)),
        status=_St.SCHEDULED, type=consulta.type,
    )
    try:
        confere(_entregar(passada, 'booked', 1) == [],
                'consulta que ja aconteceu nao vira aviso de marcacao')
    finally:
        passada.delete()

    # Cancelada entre o evento e a entrega: o "marcada" nao sai.
    futuro.status = _St.CANCELLED
    futuro.save(update_fields=['status'])
    depois = Delivery.objects.filter(appointment=futuro).count()
    confere(_entregar(futuro, 'booked', 99) == [],
            'agendamento ja cancelado nao recebe aviso de "marcada"')
    confere(_entregar(futuro, 'rescheduled', 98) == [],
            'nem de "remarcada"')
    # E o contrario: "cancelada" so sai se estiver cancelada mesmo.
    confere(_entregar(futuro, 'cancelled', 97) != [],
            'mas o aviso de cancelamento sai, porque ela esta cancelada')
    futuro.status = _St.SCHEDULED
    futuro.save(update_fields=['status'])
    confere(_entregar(futuro, 'cancelled', 96) == [],
            'e nao sai para agendamento que esta de pe')
finally:
    from communications.models import DeliveryAttempt as _Da

    _entregas = Delivery.objects.filter(appointment=futuro)
    _Da.objects.filter(delivery__in=_entregas).delete()
    _entregas.delete()
    futuro.delete()

print('=== 7. o aviso nao sai de dentro da requisicao ===')
# Mesma regra do §2 que a confirmacao de horario quebrou em 06/10: quem
# entrega e o worker. Aqui nasce de evento, e o dispatcher roda la.
vista = Path(raiz, 'scheduling', 'views.py').read_text(encoding='utf-8')
confere('deliver_appointment_notice' not in vista,
        'nenhuma view chama a entrega do aviso diretamente')
handlers = Path(raiz, 'communications', 'handlers.py').read_text(encoding='utf-8')
confere('deliver_appointment_notice' in handlers,
        'quem chama e o consumidor do evento, que roda no worker')

PatientContact.objects.filter(
    patient=consulta.patient, email='aviso-de-horario@roteiro.local',
).delete()

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - o paciente e avisado, e a mensagem diz onde é.')
