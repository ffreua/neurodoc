"""A nova tentativa do worker não repete mensagem que já saiu (auditoria de 2026-10, C1/C2).

A confirmação de horário e o reenvio de documento saem por tarefa com
`autoretry_for=(Exception,)`. A regra existe para a falha **antes** do
envio — o banco que piscou ao abrir o horário — e valia também para a
falha **depois** dele: o SMS saía, a trilha de auditoria (ou a gravação
da entrega) estourava, e a tarefa recomeçava do zero.

- **confirmação:** a repetição criava outra `Delivery` e mandava outro SMS;
  o paciente recebia a confirmação duas vezes;
- **reenvio de documento:** a repetição revogava os links que a primeira
  volta acabara de mandar e mandava links novos — o paciente recebia dois
  SMS, **o primeiro com link morto**.

O roteiro injeta a falha nos dois pontos (depois e antes do envio) e roda a
tarefa como o worker roda, com a nova tentativa de verdade (`apply()`
executa a repetição no mesmo processo). E confere o outro lado: dois
cliques continuam sendo dois envios — reenviar é justamente o pedido.

Tudo dentro de transação desfeita; o provedor é simulado.

    docker compose exec -T app python manage.py shell < checks/check_sms_sem_repeticao.py
"""
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.backends.postgresql.psycopg_any import DateTimeTZRange
from django.utils import timezone

import audit.services as audit_services
from communications import access, services
from communications.models import Delivery, DeliveryChannel, DocumentAccessToken
from communications.tasks import deliver_document_task, send_confirmation_task
from documents.models import MedicalDocument
from patients.models import Patient, PatientContact, RegistrationStage
from scheduling.models import Appointment
from tenancy.models import Membership, Tenant

falhas = []
SUFIXO = secrets.token_hex(3)


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Provedor:
    """SMS e e-mail simulados: guardam o texto em vez de enviar."""

    def __init__(self):
        self.mensagens = []

    def sms(self, phone, message, **_):
        self.mensagens.append(('sms', message))
        return {'id': f'roteiro-{len(self.mensagens)}'}

    def email(self, to, subject, message, **_):
        self.mensagens.append(('email', message))

    def quantas(self, canal):
        return sum(1 for c, _ in self.mensagens if c == canal)


def falha_na_primeira(funcao, quando='depois'):
    """Embrulha `funcao` para estourar só na primeira chamada.

    `depois`: a função roda (o SMS sai) e só então estoura — o caso que
    repetia. `antes`: estoura sem rodar — o caso que a nova tentativa existe
    para cobrir, e que tem de continuar coberto.
    """
    estado = {'chamadas': 0}

    def embrulho(*a, **k):
        estado['chamadas'] += 1
        if estado['chamadas'] == 1 and quando == 'antes':
            raise RuntimeError('falha simulada antes do envio')
        resultado = funcao(*a, **k)
        if estado['chamadas'] == 1 and quando == 'depois':
            raise RuntimeError('falha simulada depois do envio')
        return resultado
    return embrulho


class Remendo:
    """Troca atributos e devolve os originais na saída, aconteça o que acontecer."""

    def __init__(self, *trocas):
        self.trocas = trocas

    def __enter__(self):
        self.originais = [(alvo, nome, getattr(alvo, nome)) for alvo, nome, _ in self.trocas]
        for alvo, nome, novo in self.trocas:
            setattr(alvo, nome, novo)

    def __exit__(self, *exc):
        for alvo, nome, original in self.originais:
            setattr(alvo, nome, original)


def links_mandados(provedor):
    return [m.split('/d/')[1].split('/')[0] for _, m in provedor.mensagens if '/d/' in m]


tenant = Tenant.objects.get(slug='demo-clinica-a')
medico = Membership.objects.filter(tenant=tenant, user__email='doctor-a@demo.neurodoc.local').first()

with transaction.atomic():
    agora = timezone.now()
    paciente = Patient.objects.create(
        tenant=tenant, full_name=f'PACIENTE SEM REPETICAO {SUFIXO}',
        registration_stage=RegistrationStage.COMPLETE,
    )
    contato = PatientContact.objects.create(
        tenant=tenant, patient=paciente, name=paciente.full_name,
        email=f'repeticao.{SUFIXO}@example.invalid', phone='11977776666',
        verified_email_at=agora, verified_phone_at=agora,
        authorized_for_documents=True, email_enabled=True, sms_enabled=True,
    )
    inicio = timezone.localtime() + timedelta(days=3)
    inicio = inicio.replace(hour=10, minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(minutes=40)
    horario = Appointment.objects.create(
        tenant=tenant, patient=paciente, physician_membership=medico,
        starts_at=inicio, ends_at=fim, occupied_range=DateTimeTZRange(inicio, fim),
    )
    documento = MedicalDocument.objects.create(
        tenant=tenant, patient=paciente, physician=medico, kind='prescription', status='issued',
    )

    def confirmar():
        return send_confirmation_task.apply(
            args=[str(horario.id), DeliveryChannel.SMS, medico.user_id, str(contato.id)],
        )

    def reenviar():
        return deliver_document_task.apply(args=[str(documento.id)], kwargs={'force_new_link': True})

    def confirmacoes():
        return Delivery.objects.filter(appointment=horario, channel=DeliveryChannel.SMS).count()

    def entregas_novas(antes):
        # O histórico é protegido (a tentativa referencia a entrega), então
        # o roteiro conta a partir de onde parou em vez de apagar.
        return confirmacoes() - antes

    print('=== 1. Confirmação: a falha depois do envio não repete o SMS ===')
    antes = confirmacoes()
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email),
                 (audit_services, 'record_audit_event',
                  falha_na_primeira(audit_services.record_audit_event, 'depois'))):
        confirmar()
    conferir('um SMS só, com a trilha estourando depois do envio', p.quantas('sms') == 1, p.mensagens)
    conferir('uma entrega só no histórico do horário', entregas_novas(antes) == 1, entregas_novas(antes))

    print('=== 2. Confirmação: a falha antes do envio continua sendo tentada de novo ===')
    antes = confirmacoes()
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email),
                 (services, '_confirmation_message',
                  falha_na_primeira(services._confirmation_message, 'antes'))):
        confirmar()
    conferir('a nova tentativa manda o SMS', p.quantas('sms') == 1, p.mensagens)
    conferir('e registra uma entrega', entregas_novas(antes) == 1, entregas_novas(antes))

    print('=== 3. Confirmação: dois cliques continuam sendo dois envios ===')
    antes = confirmacoes()
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email)):
        confirmar()
        confirmar()
    conferir('dois SMS', p.quantas('sms') == 2, p.mensagens)
    conferir('duas entregas numeradas', entregas_novas(antes) == 2, entregas_novas(antes))

    print('=== 4. Reenvio de documento: a falha depois do envio não mata o link mandado ===')
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email),
                 (services, '_send', falha_na_primeira(services._send, 'depois'))):
        reenviar()
    conferir('uma mensagem por canal', sorted(c for c, _ in p.mensagens) == ['email', 'sms'], p.mensagens)
    mandados = links_mandados(p)
    vivos = [r for r in mandados if access.resolve_token(r) is not None]
    conferir('todo link que chegou ao paciente abre', len(mandados) == 2 and len(vivos) == 2,
             f'{len(vivos)} de {len(mandados)}')

    print('=== 5. Reenvio de documento: a falha antes do envio continua sendo tentada de novo ===')
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email),
                 (access, 'revoke_previous_tokens',
                  falha_na_primeira(access.revoke_previous_tokens, 'antes'))):
        reenviar()
    conferir('a nova tentativa manda uma mensagem por canal',
             sorted(c for c, _ in p.mensagens) == ['email', 'sms'], p.mensagens)
    mandados = links_mandados(p)
    conferir('e os dois links abrem', all(access.resolve_token(r) for r in mandados) and len(mandados) == 2)

    print('=== 6. Reenvio de documento: dois cliques continuam revogando o anterior ===')
    p = Provedor()
    with Remendo((services, 'send_sms', p.sms), (services, 'send_email', p.email)):
        reenviar()
        primeiro = links_mandados(p)
        reenviar()
    segundo = links_mandados(p)[len(primeiro):]
    conferir('cada clique manda uma mensagem por canal', len(primeiro) == 2 and len(segundo) == 2, p.mensagens)
    conferir('os links do primeiro clique morreram', not any(access.resolve_token(r) for r in primeiro))
    conferir('os do segundo abrem', all(access.resolve_token(r) for r in segundo))
    conferir('vivos são só os do último clique',
             DocumentAccessToken.objects.filter(document=documento, revoked_at__isnull=True).count() == 2)

    transaction.set_rollback(True)

print('=== 7. Nada ficou gravado ===')
conferir('o paciente do roteiro não existe mais', not Patient.objects.filter(full_name__endswith=SUFIXO).exists())

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: a nova tentativa do worker não repete mensagem que já saiu.')
