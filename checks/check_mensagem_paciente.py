"""O que o paciente le no SMS e no e-mail.

Encontrado em uso real, num teste que o proprio medico fez para si mesmo.
O SMS de confirmacao dizia:

    "Confirme respondendo a esta mensagem ou ligue para a clinica."

**Ninguem le resposta de SMS.** Nao ha webhook, nao ha caixa de entrada,
nao ha nada. O paciente respondia "confirmo" e a mensagem morria no
provedor -- ele achando que tinha confirmado, a clinica sem saber que
tinha alguem contando com aquele horario. Pedir uma acao que o sistema nao
recebe e pior que nao pedir nada.

O lembrete automatico tinha outro problema, da mesma familia: apresentava-se
como "Lembrete NeuroDoc". O paciente nao sabe o que e NeuroDoc -- ele
conhece o consultorio onde marcou. Chegava como remetente desconhecido, que
e o que se apaga sem ler.

O que este roteiro cobra:

- nenhuma mensagem pede resposta, e as duas dizem que nao respondam;
- as duas apontam o telefone como o caminho, e trazem o numero quando ele
  esta cadastrado;
- o SMS **cabe em 160** mesmo com nome patologico, e nao termina no meio de
  uma palavra -- o corte cego `texto[:160]` que existia aqui decepava
  justamente o fim, que e onde esta a instrucao;
- o lembrete se apresenta pela clinica;
- **o horario sai no fuso local.** O lembrete usava `starts_at` cru, que
  imprime em UTC: a mensagem chegava certa e com a hora errada em tres
  horas -- o paciente aparecendo cedo ou perdendo a consulta.
"""
from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.utils import timezone

from communications import services
from communications.models import DeliveryChannel
from scheduling.models import Appointment

falhas = []


def conferir(rotulo, obtido, esperado):
    ok = obtido == esperado
    print(f'  {"ok " if ok else "FALHA"}  {rotulo:58} -> {obtido}')
    if not ok:
        falhas.append(f'{rotulo}: esperado {esperado}, obtido {obtido}')


agendamento = (
    Appointment.objects
    .select_related('tenant', 'patient', 'physician_membership__user')
    .first()
)
assert agendamento is not None, 'a semeadura precisa de ao menos um agendamento'
from tenancy.models import ClinicProfile

perfil = ClinicProfile.objects.filter(tenant_id=agendamento.tenant_id).first()
telefone_antes = getattr(perfil, 'phone', None)
endereco_antes = {
    campo: getattr(perfil, campo, '')
    for campo in ['address_line', 'address_district', 'city', 'state', 'postal_code']
} if perfil is not None else None

PEDIDOS_DE_RESPOSTA = [
    'respondendo a esta', 'responda esta mensagem', 'responda com',
    'confirme respondendo', 'responder este sms',
]

try:
    print('\n1. O SMS informa, e nao pede resposta')
    sms = services._confirmation_message(agendamento, DeliveryChannel.SMS)
    print(f'     [{sms}]')
    for frase in PEDIDOS_DE_RESPOSTA:
        if frase in sms.lower():
            falhas.append(f'o SMS ainda pede resposta: "{frase}"')
    conferir('nao pede resposta', any(f in sms.lower() for f in PEDIDOS_DE_RESPOSTA), False)
    conferir('diz para nao responder', 'nao responda' in sms.lower(), True)
    conferir('aponta o telefone como caminho', 'ligue' in sms.lower(), True)
    conferir('traz a data e a hora', '/' in sms and ':' in sms, True)

    print('\n2. O SMS cabe em 160, e nao termina no meio da palavra')
    conferir('tamanho', len(sms) <= services.SMS_MAX_CHARS, True)
    conferir('nao termina com palavra cortada', sms.endswith(('.', ':')), True)

    print('\n3. Nomes patologicos nao estouram nem decepam')
    # O caso que o corte cego escondia: texto que cresce, e o fim -- onde
    # esta a instrucao -- sumindo sem ninguem perceber.
    for clinica, medico in [
        ('Consultorio Dr Fernando', 'Fernando Freua'),
        ('Centro de Neurologia e Neurocirurgia Avancada de Sao Paulo', 'Dr. Fernando Kok de Sa Freua'),
        ('C', 'F'),
        ('Instituto Nacional de Doencas Neurologicas Raras e Neurogenetica', 'Professor Doutor Fernando Kok de Sa Freua Junior'),
    ]:
        texto = services._encurtar_para_sms(
            services.CONFIRMATION_SMS_TEMPLATE, clinica, medico,
            '28/09 às 13:00', ': (11) 3456-7890',
        )
        ok_tamanho = len(texto) <= services.SMS_MAX_CHARS
        ok_fim = texto.endswith(('.', ':')) or not texto.endswith(' ')
        print(f'     {len(texto):3} chars  [{texto[:72]}...]')
        if not ok_tamanho:
            falhas.append(f'estourou 160 com clinica={clinica!r}')
        if not ok_fim:
            falhas.append(f'terminou cortado com clinica={clinica!r}')
    conferir('todos os casos couberam', all(
        len(services._encurtar_para_sms(
            services.CONFIRMATION_SMS_TEMPLATE, c, m, '28/09 às 13:00', ': (11) 3456-7890',
        )) <= services.SMS_MAX_CHARS
        for c, m in [('A' * 60, 'B' * 60), ('C', 'D')]
    ), True)

    print('\n4. O e-mail explica, e diz que a caixa nao le resposta')
    email = services._confirmation_message(agendamento, DeliveryChannel.EMAIL)
    conferir('avisa que ninguem le a resposta', 'não recebe respostas' in email, True)
    conferir('manda ligar', 'ligue para a clínica' in email, True)
    conferir('oferece confirmar, remarcar e cancelar',
             all(v in email.lower() for v in ['confirmar', 'remarcar', 'cancelar']), True)
    conferir('avisa que nao ha informacao clinica', 'não contém informação clínica' in email, True)
    for frase in PEDIDOS_DE_RESPOSTA:
        if frase in email.lower():
            falhas.append(f'o e-mail ainda pede resposta: "{frase}"')

    print('\n5. O telefone da clinica entra quando esta cadastrado')
    # Cria o perfil se a clinica nao tiver: esta secao exercita codigo
    # novo, e pular por falta de dado de semeadura deixaria justamente a
    # parte nao testada -- que e como um caminho novo chega a producao sem
    # ninguem ter passado por ele.
    perfil_criado_aqui = False
    if perfil is None:
        from tenancy.models import ClinicProfile

        perfil = ClinicProfile.objects.create(tenant=agendamento.tenant)
        perfil_criado_aqui = True
    if True:
        perfil.phone = '(11) 3456-7890'
        perfil.save(update_fields=['phone'])
        agendamento.tenant.refresh_from_db()
        email2 = services._confirmation_message(agendamento, DeliveryChannel.EMAIL)
        conferir('o numero aparece no e-mail', '(11) 3456-7890' in email2, True)
        perfil.phone = ''
        perfil.save(update_fields=['phone'])
        agendamento.tenant.refresh_from_db()
        email3 = services._confirmation_message(agendamento, DeliveryChannel.EMAIL)
        conferir('sem numero cadastrado, a frase segue inteira',
                 'ligue para a clínica.' in email3, True)

        print('\n5b. O e-mail traz endereco e link de mapa somente quando ha endereco')
        perfil.address_line = 'Rua Dr. Ovidio Pires de Campos, 225'
        perfil.address_district = 'Cerqueira Cesar'
        perfil.city = 'Sao Paulo'
        perfil.state = 'SP'
        perfil.postal_code = '05403-010'
        perfil.save(update_fields=[
            'address_line', 'address_district', 'city', 'state', 'postal_code',
        ])
        email_com_endereco = services._confirmation_message(agendamento, DeliveryChannel.EMAIL)
        conferir('o endereco cadastrado aparece no e-mail',
                 'Rua Dr. Ovidio Pires de Campos, 225' in email_com_endereco, True)
        conferir('o e-mail oferece busca do endereco no Google Maps',
                 'https://www.google.com/maps/search/?api=1&query=' in email_com_endereco, True)
        for campo in ['address_line', 'address_district', 'city', 'state', 'postal_code']:
            setattr(perfil, campo, '')
        perfil.save(update_fields=[
            'address_line', 'address_district', 'city', 'state', 'postal_code',
        ])
        email_sem_endereco = services._confirmation_message(agendamento, DeliveryChannel.EMAIL)
        conferir('sem endereco, o e-mail nao inventa link de mapa',
                 'google.com/maps' in email_sem_endereco, False)

    print('\n6. O lembrete se apresenta pela clinica, nao pelo fornecedor')
    lembrete = services.REMINDER_MESSAGE_TEMPLATE.format(
        clinic='Consultorio Dr Fernando', when='28/09 às 13:00',
    )
    print(f'     [{lembrete}]')
    conferir('nao diz NeuroDoc', 'neurodoc' in lembrete.lower(), False)
    conferir('diz o nome da clinica', 'Consultorio Dr Fernando' in lembrete, True)
    conferir('tambem nao pede resposta', 'nao responda' in lembrete.lower(), True)
    conferir('cabe em 160', len(lembrete) <= services.SMS_MAX_CHARS, True)

    print('\n7. O horario do lembrete sai no fuso local')
    # `starts_at` cru imprime em UTC. A diferenca so aparece em producao,
    # com a mensagem parecendo correta e a hora errada em tres horas.
    import inspect

    fonte = inspect.getsource(services.deliver_appointment_reminder)
    conferir('usa localtime no lembrete',
             'localtime(appointment.starts_at)' in fonte, True)
    conferir('nao usa mais o horario cru',
             "appointment.starts_at.strftime" in fonte, False)

finally:
    if perfil_criado_aqui:
        perfil.delete()
        print('\n  perfil de clinica criado por este roteiro foi removido')
    elif perfil is not None and telefone_antes is not None:
        perfil.phone = telefone_antes
        for campo, valor in (endereco_antes or {}).items():
            setattr(perfil, campo, valor)
        perfil.save(update_fields=[
            'phone', 'address_line', 'address_district', 'city', 'state', 'postal_code',
        ])
        print('\n  telefone e endereco da clinica restaurados')

if falhas:
    for item in falhas:
        print('FALHA:', item)
    raise SystemExit(1)
print('\nOK: o SMS informa sem pedir resposta e cabe em 160 sem decepar a frase,')
print('    o e-mail avisa que a caixa nao le respostas, e o lembrete e da clinica.')
