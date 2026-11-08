"""O WhatsApp da recepção (1.39): o botão que abre a conversa com o lembrete.

O NeuroDoc **não envia** WhatsApp: monta o texto que a clínica escreveu com
os dados do horário e abre `wa.me` no WhatsApp da própria clínica, e quem
envia é a secretária (`communications/whatsapp.py`). Este roteiro tenta
quebrar cada peça:

1. o telefone no formato do `wa.me` — com e sem DDD, com +55, com zero na
   frente, de outro país, curto demais;
2. o nome que não grita ("MARIA DA SILVA" → "Maria da Silva");
3. os campos: lista fechada, o desconhecido fica como está e é recusado ao
   salvar, e `{paciente.__class__}` não atravessa atributo nenhum;
4. a mensagem: o padrão com e sem endereço, o texto da clínica, o dia da
   semana, e a data de Brasília às 23h30 (o UTC já é o dia seguinte);
5. de quem é o telefone: o do próprio paciente primeiro, o contato vencido
   fora, o número que não serve pulado, e sem nenhum, a recusa;
6. a rota: redireciona ao `wa.me` com o texto inteiro e com acento, registra
   na trilha **sem** telefone nem texto, recusa horário cancelado e paciente
   sem celular, 404 para outra clínica, e não aceita POST;
7. a tela de integrações: o cartão em **todos os planos** (inclusive o
   Gratuito), a prévia, salvar, recusar campo desconhecido e texto longo sem
   gravar nada, voltar ao padrão, e a secretária fora;
8. a agenda: o botão no modal (link em aba própria, sem `onclick`), o
   balcão com o botão só antes da chegada e só com telefone, e o balcão sem
   uma consulta de contatos por linha.

Tudo dentro de uma transação desfeita no fim.

    docker compose exec -T app python manage.py shell < checks/check_whatsapp_recepcao.py
"""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

from django.conf import settings as dj_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from communications import whatsapp
from communications.forms import WhatsAppTextForm
from communications.models import MessagingSettings
from patients.contacts import SELF_RELATIONSHIP
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling.models import Appointment, AppointmentStatus, AppointmentType
from tenancy.models import Membership, MembershipStatus, Tenant

falhas = []


def conferir(rotulo, ok, detalhe=''):
    print(f'  {"ok   " if ok else "FALHA"} {rotulo}' + (f' — {detalhe}' if detalhe and not ok else ''))
    if not ok:
        falhas.append(rotulo)


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=tenant.id).filter(slug__startswith='demo-').first()


def vinculo_de(t, papel):
    return Membership.objects.filter(
        tenant=t, status=MembershipStatus.ACTIVE, roles__contains=[papel],
    ).select_related('user').order_by('user__email').first()


medico = vinculo_de(tenant, 'doctor')
secretaria = vinculo_de(tenant, 'secretary')
dono = vinculo_de(tenant, 'owner') or vinculo_de(tenant, 'manager')
de_fora = vinculo_de(outra, 'secretary') or vinculo_de(outra, 'owner') if outra else None


def cliente(m):
    c = Client()
    c.force_login(m.user)
    s = c.session
    s['tenant_id'] = str(m.tenant_id)
    s.save()
    return c


def paciente(nome, *contatos):
    p = Patient.objects.create(tenant=tenant, full_name=nome, registration_stage=RegistrationStage.COMPLETE,
                               birth_date_unknown_reason='Roteiro de verificação.')
    for rel, fone, vencido in contatos:
        PatientContact.objects.create(
            tenant=tenant, patient=p, name=nome if rel == SELF_RELATIONSHIP else 'PARENTE',
            relationship=rel, phone=fone,
            valid_until=timezone.now() - timedelta(days=1) if vencido else None,
        )
    return p


def marcar(p, quando, status=AppointmentStatus.SCHEDULED):
    fim = quando + timedelta(minutes=30)
    # Encaixe: fora da grade e da exclusão de sobreposição, para o roteiro
    # não depender da agenda da demonstração ter vaga.
    return Appointment.objects.create(
        tenant=tenant, patient=p, physician_membership=medico, starts_at=quando, ends_at=fim,
        occupied_range=(quando, fim), status=status, type=AppointmentType.FOLLOW_UP,
        is_overbook=True, override_reason='Roteiro de verificação.', override_by=medico,
    )


try:
    with transaction.atomic():
        print('1. O telefone no formato do wa.me')
        for entrada, esperado in [
            ('(11) 98765-4321', '5511987654321'), ('11 3456-7890', '551134567890'),
            ('+55 11 98765-4321', '5511987654321'), ('5511987654321', '5511987654321'),
            ('011 98765-4321', '5511987654321'), ('(55) 99876-5432', '5555998765432'),
            ('+1 415 555 0100', '14155550100'), ('98765-4321', None), ('', None), ('abc', None),
        ]:
            obtido = whatsapp.normalizar_telefone(entrada)
            conferir(f'{entrada!r} → {esperado}', obtido == esperado, obtido)

        print('2. O nome que não grita')
        conferir('MARIA DA SILVA → Maria da Silva', whatsapp.nome_proprio('MARIA DA SILVA') == 'Maria da Silva')
        conferir('DE ALMEIDA no começo continua maiúsculo',
                 whatsapp.nome_proprio('DE ALMEIDA JOSÉ') == 'De Almeida José', whatsapp.nome_proprio('DE ALMEIDA JOSÉ'))
        conferir('o acento fica', whatsapp.nome_proprio('JOÃO DOS SANTOS E SOUZA') == 'João dos Santos e Souza')

        print('3. Os campos: lista fechada')
        conferir('desconhecido apontado, sem repetir',
                 whatsapp.campos_desconhecidos('{nome} {data} {nome} {cpf}') == ['nome', 'cpf'])
        conferir('o desconhecido fica como está ao preencher',
                 whatsapp.preencher('{x} {hora}', {'hora': '10:00'}) == '{x} 10:00')
        ataque = 'Oi {paciente.__class__} {paciente.__init__.__globals__}'
        conferir('atributo não atravessa', whatsapp.preencher(ataque, {'paciente': 'Maria'}) == ataque)
        form = WhatsAppTextForm({'whatsapp_texto': ataque})
        conferir('e o formulário recusa', not form.is_valid())
        conferir('a recusa é em português e cita o campo',
                 'Campo que o sistema não conhece' in str(form.errors) and 'paciente.__class__' in str(form.errors))
        form = WhatsAppTextForm({'whatsapp_texto': 'x' * (whatsapp.MAX_CARACTERES + 1)})
        conferir(f'mais de {whatsapp.MAX_CARACTERES} caracteres recusado', not form.is_valid())

        print('4. A mensagem')
        MessagingSettings.objects.update_or_create(tenant=tenant, defaults={'whatsapp_texto': ''})
        brasilia = ZoneInfo('America/Sao_Paulo')
        # Terça, 23h30 em Brasília: 02h30 de quarta em UTC.
        base = timezone.localdate() + timedelta(days=14)
        terca = base + timedelta(days=(1 - base.weekday()) % 7)
        noite = datetime(terca.year, terca.month, terca.day, 23, 30, tzinfo=brasilia)
        maria = paciente('MARIA DA SILVA ROTEIRO', (SELF_RELATIONSHIP, '(11) 98765-4321', False))
        h = marcar(maria, noite)
        h = Appointment.objects.select_related('patient', 'tenant', 'physician_membership__user').get(id=h.id)
        texto = whatsapp.mensagem(h)
        conferir('primeiro nome sem grito', 'Olá, Maria!' in texto, texto[:40])
        conferir('a data de Brasília, e não a do UTC', f'{terca:%d/%m/%Y}' in texto, texto)
        conferir('o dia da semana certo', 'terça-feira' in texto)
        conferir('a hora local', 'às 23:30' in texto)
        conferir('o médico', (medico.user.get_full_name() or medico.user.email) in texto)
        conferir('nenhum campo sobrando', '{' not in texto and '}' not in texto, texto)
        endereco = whatsapp._dados_da_clinica(tenant)['endereco']
        conferir('com endereço cadastrado ele entra, sem endereço a linha some',
                 ('Endereço:' in texto) == bool(endereco), f'endereco={endereco!r}')
        MessagingSettings.objects.filter(tenant=tenant).update(
            whatsapp_texto='Oi {paciente}, {tipo} em {data} às {hora} — {clinica}. Responda SIM.')
        texto = whatsapp.mensagem(h)
        conferir('o texto da clínica vale', texto.startswith(f'Oi Maria da Silva Roteiro, {h.get_type_display()} em'), texto)

        print('5. De quem é o telefone')
        p = paciente('PACIENTE COM PARENTE',
                     ('Mãe', '(21) 99999-0000', False), (SELF_RELATIONSHIP, '(11) 91234-5678', False))
        conferir('o do próprio paciente primeiro', whatsapp.telefone_do_paciente(marcar(p, noite + timedelta(hours=1))) == '5511912345678')
        p = paciente('PACIENTE VENCIDO', (SELF_RELATIONSHIP, '(11) 91111-1111', True), ('Filho', '(31) 92222-2222', False))
        conferir('contato vencido fora', whatsapp.telefone_do_paciente(marcar(p, noite + timedelta(hours=2))) == '5531922222222')
        p = paciente('PACIENTE NUMERO RUIM', (SELF_RELATIONSHIP, '9876-5432', False), ('Irmã', '(41) 93333-3333', False))
        conferir('número sem DDD pulado', whatsapp.telefone_do_paciente(marcar(p, noite + timedelta(hours=3))) == '5541933333333')
        sem = paciente('PACIENTE SEM TELEFONE', (SELF_RELATIONSHIP, '', False))
        h_sem = marcar(sem, noite + timedelta(hours=4))
        try:
            whatsapp.telefone_do_paciente(h_sem)
            conferir('sem celular, SemTelefone', False)
        except whatsapp.SemTelefone:
            conferir('sem celular, SemTelefone', True)

        print('6. A rota')
        sec = cliente(secretaria)
        antes = AuditEvent.objects.filter(action='scheduling.whatsapp_aberto').count()
        r = sec.get(reverse('scheduling:whatsapp', args=[h.id]))
        destino = r.get('Location', '')
        conferir('redireciona ao wa.me com o número', r.status_code == 302
                 and destino.startswith('https://wa.me/5511987654321?text='), f'{r.status_code} {destino[:60]}')
        recebido = parse_qs(urlparse(destino).query).get('text', [''])[0]
        conferir('o texto chega inteiro e com acento', recebido == whatsapp.mensagem(h) and '—' in recebido, recebido)
        evento = AuditEvent.objects.filter(action='scheduling.whatsapp_aberto', object_id=h.id).first()
        conferir('um evento a mais', AuditEvent.objects.filter(action='scheduling.whatsapp_aberto').count() == antes + 1)
        conferir('a trilha registra a abertura', evento is not None and evento.object_id == h.id)
        conferir('a trilha sem telefone nem texto', evento is not None
                 and '98765' not in str(evento.integrity_metadata) and 'Maria' not in str(evento.integrity_metadata))
        r = sec.get(reverse('scheduling:whatsapp', args=[h_sem.id]))
        conferir('sem celular volta à agenda', r.status_code == 302 and 'wa.me' not in r.get('Location', ''))
        cancelado = marcar(maria, noite + timedelta(days=1), AppointmentStatus.CANCELLED)
        r = sec.get(reverse('scheduling:whatsapp', args=[cancelado.id]))
        conferir('cancelado volta à agenda', r.status_code == 302 and 'wa.me' not in r.get('Location', ''))
        conferir('POST não é aceito', sec.post(reverse('scheduling:whatsapp', args=[h.id])).status_code == 405)
        if de_fora:
            conferir('outra clínica: 404', cliente(de_fora).get(reverse('scheduling:whatsapp', args=[h.id])).status_code == 404)

        print('7. A tela de integrações')
        Tenant.objects.filter(id=tenant.id).update(plan='free')
        gestor = cliente(dono)
        pagina = gestor.get(reverse('messaging:settings')).content.decode()
        conferir('o cartão aparece no plano Gratuito', 'id="whatsapp"' in pagina and 'WhatsApp da recepção' in pagina)
        conferir('a lista de campos', '{primeiro_nome}' in pagina and '{telefone_clinica}' in pagina)
        conferir('a prévia com o paciente de exemplo', 'Oi Maria da Silva, Retorno em 25/11/2026' in pagina)
        r = gestor.post(reverse('messaging:save-whatsapp'),
                        {'whatsapp_texto': 'Olá {primeiro_nome}! Consulta em {data} às {hora}.'})
        conferir('salvar volta ao cartão', r.status_code == 302 and r['Location'].endswith('#whatsapp'))
        conferir('e grava', MessagingSettings.objects.get(tenant=tenant).whatsapp_texto
                 == 'Olá {primeiro_nome}! Consulta em {data} às {hora}.')
        r = gestor.post(reverse('messaging:save-whatsapp'), {'whatsapp_texto': 'Oi {nome_do_paciente}'})
        conferir('campo desconhecido recusado na tela', r.status_code == 200
                 and 'Campo que o sistema não conhece' in r.content.decode())
        conferir('e nada gravado', MessagingSettings.objects.get(tenant=tenant).whatsapp_texto.startswith('Olá {primeiro_nome}'))
        r = gestor.post(reverse('messaging:save-whatsapp'), {'whatsapp_texto': 'x', 'padrao': '1'})
        conferir('voltar ao padrão esvazia', r.status_code == 302
                 and MessagingSettings.objects.get(tenant=tenant).whatsapp_texto == '')
        conferir('e o padrão vale de novo', whatsapp.mensagem(h).startswith('Olá, Maria! Aqui é da'))
        pagina = gestor.get(reverse('messaging:settings')).content.decode()
        conferir('a caixa nasce com o texto padrão para editar', 'Passando para lembrar da sua' in pagina)
        padrao_do_navegador = whatsapp.padrao_da_clinica(tenant).replace('\n', '\r\n')
        r = gestor.post(reverse('messaging:save-whatsapp'), {'whatsapp_texto': padrao_do_navegador})
        conferir('salvar o padrão sem mudar (com CR+LF) continua padrão', r.status_code == 302
                 and MessagingSettings.objects.get(tenant=tenant).whatsapp_texto == '')
        r = sec.post(reverse('messaging:save-whatsapp'), {'whatsapp_texto': 'Invasão {data}'})
        conferir('a secretária não grava', r.status_code in (403, 404)
                 and MessagingSettings.objects.get(tenant=tenant).whatsapp_texto == '', r.status_code)

        print('8. A agenda')
        modal = open('templates/scheduling/_booking_modals.html', encoding='utf-8').read()
        trecho = modal[modal.index('id="slot-whatsapp"') - 80: modal.index('id="slot-whatsapp"') + 200]
        conferir('o botão no modal, em aba própria', 'target="_blank"' in trecho and 'rel="noopener"' in trecho)
        conferir('sem onclick', 'onclick' not in trecho)
        js = open('static/scheduling/agenda.js', encoding='utf-8').read()
        conferir('o JS põe o horário no endereço', "'/whatsapp/'" in js and 'whatsappLink.hidden' in js)
        semana = sec.get(reverse('scheduling:week') + f'?physician={medico.id}&date={terca:%Y-%m-%d}').content.decode()
        conferir('a semana desenha o botão', 'id="slot-whatsapp"' in semana)
        chegou = marcar(paciente('PACIENTE JA CHEGOU', (SELF_RELATIONSHIP, '(11) 95555-5555', False)),
                        noite - timedelta(hours=5), AppointmentStatus.CHECKED_IN)
        balcao = sec.get(reverse('scheduling:desk') + f'?date={terca:%Y-%m-%d}').content.decode()
        conferir('balcão: botão para quem vem', reverse('scheduling:whatsapp', args=[h.id]) in balcao)
        conferir('balcão: sem botão para quem já chegou', reverse('scheduling:whatsapp', args=[chegou.id]) not in balcao)
        conferir('balcão: sem botão sem telefone', reverse('scheduling:whatsapp', args=[h_sem.id]) not in balcao)

        def consultas_do_balcao():
            with CaptureQueriesContext(connection) as ctx:
                sec.get(reverse('scheduling:desk') + f'?date={terca:%Y-%m-%d}')
            return len(ctx.captured_queries)

        n1 = consultas_do_balcao()
        for i in range(5):
            marcar(paciente(f'PACIENTE VOLUME {i}', (SELF_RELATIONSHIP, f'(11) 9600{i}-0000', False)),
                   noite - timedelta(minutes=40 * (i + 1)))
        n2 = consultas_do_balcao()
        conferir('balcão sem consulta por linha (5 horários a mais)', n2 == n1, f'{n1} → {n2}')
        raise Desfazer
except Desfazer:
    pass

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('WhatsApp da recepção: tudo confere.')
