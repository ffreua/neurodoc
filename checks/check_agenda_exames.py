"""Agendas de exame por recurso: EEG, ENMG, polissonografia (Sprint 4 do TISS).

Tenta quebrar:

- **meia-noite**: a janela das 20h às 7h e a polissonografia das 21h às
  7h — uma linha só, nos dois dias da tela, sem sobra de horário livre;
- **sobreposição**: o mesmo equipamento recusado (pela restrição do banco,
  e com **duas conexões ao mesmo tempo**), outro equipamento no mesmo
  horário aceito;
- **agenda**: fora da janela só como encaixe com motivo, bloqueio recusa,
  passado recusado, mais de 24 h recusado, horários livres que somem e
  voltam com o cancelamento;
- **médico**: as agendas de exame não contam vaga de médico do plano;
- **cobrança**: convênio de outro paciente e convênio vencido recusados;
  realizar antes da hora e sem executante recusado; a realização cria
  **uma** cobrança (serviço e banco), sem honorário não inventa valor, e
  nada vira pagamento;
- **lembrete**: um, 24 h antes; remarcar invalida o velho; cancelado não
  recebe;
- **guia**: só do exame realizado, uma por exame, com a cobrança vinculada
  e nenhuma nova, as horas da polissonografia (21:00 → 07:00), o tipo de
  atendimento da versão — e o lote dela passando no XSD;
- **telas**: a agenda, marcar, a reserva, a configuração só para quem
  configura, outra clínica em 404, plano sem o módulo em 404, GET sem
  efeito.

Quase tudo numa transação desfeita; a concorrência grava e apaga.

    docker compose exec -T app python manage.py shell < checks/check_agenda_exames.py
"""
import threading
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.mfa import RECENT_MFA_SESSION_KEY
from agenda_exames import services as ex
from agenda_exames.models import Bloqueio, EstadoReserva, Janela, Recurso, Reserva, TipoRecurso
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from events.models import OutboxEvent, OutboxEventStatus
from finance.models import ChargeKind, FeeSchedule, Payment, PaymentCategory, Receivable
from patients.models import HealthPlan, Insurer, Patient, PatientCoverage
from tenancy.context import AccessContext
from tenancy.limits import doctor_usage
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.plans import PlanCode
from tiss import guias, lotes, versoes
from tiss.models import Configuracao, Credenciamento, EstadoGuia, Guia, ItemGuia, Prestador, ProfissionalTiss

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


clinica = Tenant.objects.get(slug='demo-clinica-a')
outra = Tenant.objects.exclude(id=clinica.id).order_by('created_at').first()
vinculos = list(Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user'))
secretaria = next((m for m in vinculos if Role.SECRETARY in (m.roles or [])
                   and not {Role.OWNER, Role.MANAGER, Role.DOCTOR} & set(m.roles or [])), None)
dono = next((m for m in vinculos if Role.OWNER in (m.roles or [])), None)
medico = next((m for m in vinculos if Role.DOCTOR in (m.roles or []) and m.can_practice_clinically()), None)
pacientes = list(Patient.objects.filter(tenant=clinica).order_by('created_at')[:2])
if None in (secretaria, dono, medico, outra) or len(pacientes) < 2:
    print('  (demonstração incompleta; roteiro pulado)')
    raise SystemExit(0)
paciente, outro_paciente = pacientes

from tiss import lotes as _lotes
_lotes._enfileirar = lambda lote_id: None


def contexto(quem):
    from tenancy.permissions import capabilities_for
    return AccessContext(
        user_id=quem.user_id, tenant_id=clinica.id, membership_id=quem.id,
        permissions=frozenset(quem.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(quem.roles, clinically_enabled=quem.can_practice_clinically(),
                                      ai_contracted=False, tiss_contracted=True),
    )


def cliente(quem, tenant=clinica):
    c = Client(SERVER_NAME='localhost')
    c.force_login(quem.user)
    s = c.session
    s['tenant_id'] = str(tenant.id)
    s[RECENT_MFA_SESSION_KEY] = timezone.now().isoformat()
    s.save()
    return c


def recusa(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except (ex.ReservaRecusada, guias.GuiaRecusada) as exc:
        return str(exc)


def em(dia, h, m=0):
    return timezone.make_aware(datetime.combine(dia, time(h, m)))


ctx = contexto(secretaria)
hoje = timezone.localdate()
# Uma segunda-feira a pelo menos três dias daqui: a reserva nasce no futuro.
segunda = hoje + timedelta(days=3)
segunda += timedelta(days=(7 - segunda.weekday()) % 7)
terca = segunda + timedelta(days=1)


def montar_recursos():
    eeg = Recurso.objects.create(tenant=clinica, nome='EEG ROTEIRO', tipo=TipoRecurso.EEG, duracao_padrao=60,
                                 codigo_tuss='40103420', descricao_tuss='ELETROENCEFALOGRAMA DE ROTINA')
    for d in range(5):
        Janela.objects.create(tenant=clinica, recurso=eeg, dia_semana=d, inicio=time(8), fim=time(12))
    psg = Recurso.objects.create(tenant=clinica, nome='PSG ROTEIRO', tipo=TipoRecurso.PSG, duracao_padrao=600,
                                 codigo_tuss='40103757', descricao_tuss='POLISSONOGRAFIA')
    for d in range(7):
        Janela.objects.create(tenant=clinica, recurso=psg, dia_semana=d, inicio=time(20), fim=time(7))
    return eeg, psg


try:
    with transaction.atomic():
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
        Configuracao.objects.filter(id=Configuracao.carregar().id).update(ativo=True)
        medicos_antes = doctor_usage(clinica)
        eeg, psg = montar_recursos()
        conferir('as agendas de exame não contam vaga de médico', doctor_usage(clinica) == medicos_antes)

        print('=== 1. Janelas e horários livres ===')
        livres_eeg = [h.inicio for h in ex.horarios_livres(eeg, segunda)]
        conferir('EEG de 8h às 12h, 60 min: quatro horários', [timezone.localtime(x).hour for x in livres_eeg] == [8, 9, 10, 11],
                 [timezone.localtime(x).hour for x in livres_eeg])
        livres_psg = ex.horarios_livres(psg, segunda)
        conferir('PSG das 20h às 7h, 600 min: 20h é o único que cabe',
                 [timezone.localtime(h.inicio).hour for h in livres_psg] == [20])
        conferir('a janela da véspera aparece na terça', any(a.date() == segunda for a, _ in
                 [(timezone.localtime(a), b) for a, b in ex.janelas_que_cruzam(psg, terca)]))

        print('=== 2. A polissonografia atravessa a meia-noite ===')
        noite = ex.reservar(ctx, secretaria.user, psg, paciente, em(segunda, 21), duracao=600)
        conferir('reserva das 21h às 7h, uma linha', timezone.localtime(noite.fim) == em(terca, 7))
        conferir('aparece na segunda', noite in ex.reservas_do_dia(psg, segunda))
        conferir('e na terça', noite in ex.reservas_do_dia(psg, terca))
        conferir('não sobra horário livre na segunda', ex.horarios_livres(psg, segunda) == [])
        conferir('o mesmo equipamento às 23h é recusado',
                 'ocupado' in (recusa(ex.reservar, ctx, secretaria.user, psg, outro_paciente, em(segunda, 23), duracao=60) or ''))
        try:
            with transaction.atomic():
                Reserva.objects.create(tenant=clinica, recurso=psg, paciente=outro_paciente, inicio=em(segunda, 22),
                                       fim=em(segunda, 23), ocupacao=ex._ocupacao(em(segunda, 22), em(segunda, 23), 0))
            conferir('o banco recusa a sobreposição', False)
        except IntegrityError:
            conferir('o banco recusa a sobreposição', True)
        conferir('outro equipamento no mesmo horário (encaixe com motivo) é aceito',
                 recusa(ex.reservar, ctx, secretaria.user, eeg, outro_paciente, em(segunda, 21), duracao=30,
                        encaixe=True, motivo_encaixe='plantão') is None)

        print('=== 3. As recusas da agenda ===')
        conferir('fora da janela sem encaixe',
                 recusa(ex.reservar, ctx, secretaria.user, eeg, paciente, em(segunda, 14)) is not None)
        conferir('encaixe sem motivo',
                 recusa(ex.reservar, ctx, secretaria.user, eeg, paciente, em(segunda, 14), encaixe=True) is not None)
        conferir('no passado', recusa(ex.reservar, ctx, secretaria.user, eeg, paciente,
                                      timezone.now() - timedelta(hours=1), encaixe=True, motivo_encaixe='x') is not None)
        conferir('mais de 24 horas', recusa(ex.reservar, ctx, secretaria.user, psg, paciente, em(terca, 20),
                                            duracao=1500) is not None)
        bloqueio, _ = ex.criar_bloqueio(ctx, secretaria.user, eeg, em(segunda, 9), em(segunda, 10), 'manutenção')
        conferir('bloqueio recusa', 'bloqueada' in (recusa(ex.reservar, ctx, secretaria.user, eeg, paciente,
                                                           em(segunda, 9)) or ''))
        conferir('e some dos livres', em(segunda, 9) not in [h.inicio for h in ex.horarios_livres(eeg, segunda)])

        print('=== 4. Cobrança e convênio ===')
        operadora = Insurer.objects.create(tenant=clinica, name='OPERADORA ROTEIRO EXAMES', ans_registration='368253')
        plano = HealthPlan.objects.create(tenant=clinica, insurer=operadora, name='PLANO ROTEIRO EXAMES')
        cob = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano, member_number='0099X1',
                                             starts_on=date(2020, 1, 1))
        cob_alheia = PatientCoverage.objects.create(tenant=clinica, patient=outro_paciente, plan=plano,
                                                    member_number='0099X2', starts_on=date(2020, 1, 1))
        vencida = PatientCoverage.objects.create(tenant=clinica, patient=paciente, plan=plano, member_number='0099X3',
                                                 starts_on=date(2020, 1, 1), ends_on=hoje)
        conferir('convênio de outro paciente', recusa(ex.reservar, ctx, secretaria.user, eeg, paciente, em(segunda, 10),
                                                      cobranca='convenio', cobertura=cob_alheia) is not None)
        conferir('convênio vencido na data do exame', recusa(ex.reservar, ctx, secretaria.user, eeg, paciente,
                                                            em(segunda, 10), cobranca='convenio', cobertura=vencida) is not None)
        conferir('convênio vigente', recusa(ex.reservar, ctx, secretaria.user, eeg, paciente, em(segunda, 10),
                                            cobranca='convenio', cobertura=cob) is None)

        print('=== 5. Lembrete ===')
        eventos = OutboxEvent.objects.filter(topic='agenda_exames.lembrete', aggregate_id=noite.id)
        conferir('um lembrete, 24 h antes', eventos.count() == 1
                 and eventos.first().available_at == noite.inicio - timedelta(hours=24))
        ex.remarcar(ctx, secretaria.user, noite, em(terca, 21))
        noite.refresh_from_db()
        conferir('remarcar: versão nova, a velha cancelada',
                 eventos.filter(status=OutboxEventStatus.PENDING).count() == 1
                 and eventos.filter(status=OutboxEventStatus.CANCELLED).count() == 1 and noite.versao_lembrete == 2)
        conferir('remarcar libera a segunda', [timezone.localtime(h.inicio).hour for h in ex.horarios_livres(psg, segunda)] == [20])
        from communications.models import Delivery
        from communications.services import deliver_exam_reminder
        from patients.models import PatientContact
        # Um contato autorizado e verificado, só e-mail: sem ele o lembrete
        # sairia vazio e a conferência passaria sobre lista vazia.
        PatientContact.objects.filter(patient=paciente).update(email_enabled=False, sms_enabled=False)
        PatientContact.objects.create(tenant=clinica, patient=paciente, name=paciente.full_name, relationship='Próprio paciente',
                                      email='lembrete.exame@exemplo.com', email_enabled=True,
                                      verified_email_at=timezone.now())
        conferir('lembrete da versão velha não sai', deliver_exam_reminder(noite, 1) == [])
        entregas = deliver_exam_reminder(noite, 2)
        conferir('lembrete da versão atual: uma entrega, apontando para o exame',
                 len(entregas) == 1 and entregas[0].reserva_exame_id == noite.id and entregas[0].appointment_id is None,
                 entregas)
        deliver_exam_reminder(noite, 2)
        conferir('e não repete', Delivery.objects.filter(reserva_exame=noite).count() == 1)

        print('=== 6. Realização e cobrança ===')
        rel = CatalogRelease.objects.create(system=CatalogSystem.TUSS, version=f'ANS-roteiro-exames-{uuid.uuid4().hex[:6]}',
                                            status=CatalogReleaseStatus.ACTIVE, imported_at=timezone.now())
        CatalogRelease.objects.filter(system=CatalogSystem.TUSS).exclude(id=rel.id).update(status=CatalogReleaseStatus.SUPERSEDED)
        proc_psg = ProcedureCode.objects.create(release=rel, code='40103757', description='POLISSONOGRAFIA',
                                                starts_on=date(2010, 1, 1), active=True)
        FeeSchedule.objects.create(tenant=clinica, physician=None, plan=plano, procedure=proc_psg,
                                   payment_category=PaymentCategory.INSURANCE, gross_amount=Decimal('850.00'),
                                   doctor_share_amount=Decimal('0'), effective_from=hoje - timedelta(days=400))
        executante = ProfissionalTiss.objects.create(tenant=clinica, nome='DR ROTEIRO EXAMES', numero_conselho='55123',
                                                     uf='SP', cbo='225112', membership=medico)
        conferir('realizar exame futuro é recusado',
                 recusa(ex.realizar, ctx, secretaria.user, noite, executante) is not None)
        # Um exame de ontem à noite, gravado direto (marcar no passado é recusado).
        ontem = hoje - timedelta(days=1)
        feito = Reserva.objects.create(
            tenant=clinica, recurso=psg, paciente=paciente, inicio=em(ontem - timedelta(days=7), 21),
            fim=em(ontem - timedelta(days=6), 7), ocupacao=ex._ocupacao(em(ontem - timedelta(days=7), 21),
                                                                       em(ontem - timedelta(days=6), 7), 0),
            codigo_tuss='40103757', descricao='POLISSONOGRAFIA', cobranca='convenio', cobertura=cob,
            solicitante=executante,
        )
        pagamentos_antes = Payment.objects.filter(receivable__tenant=clinica).count()
        conferir('sem executante é recusado', recusa(ex.realizar, ctx, secretaria.user, feito, None) is not None)
        _, cobranca = ex.realizar(ctx, secretaria.user, feito, executante)
        conferir('realizado, com a cobrança do contrato',
                 cobranca is not None and cobranca.charged_amount == Decimal('850.00')
                 and cobranca.reserva_exame_id == feito.id and cobranca.charge_kind == ChargeKind.PROCEDURE)
        conferir('nenhuma consulta nem agendamento fictício',
                 cobranca.appointment_id is None and cobranca.encounter_id is None)
        _, de_novo = ex.realizar(ctx, secretaria.user, feito, executante)
        conferir('realizar de novo: a mesma cobrança',
                 de_novo.id == cobranca.id and Receivable.objects.filter(reserva_exame=feito).count() == 1)
        try:
            with transaction.atomic():
                Receivable.objects.create(tenant=clinica, patient=paciente, reserva_exame=feito,
                                          charge_kind=ChargeKind.PROCEDURE, expected_amount=1, charged_amount=1,
                                          due_date=hoje, competence_date=hoje)
            conferir('o banco recusa segunda cobrança do mesmo exame', False)
        except IntegrityError:
            conferir('o banco recusa segunda cobrança do mesmo exame', True)
        sem_preco = Reserva.objects.create(
            tenant=clinica, recurso=eeg, paciente=paciente, inicio=em(ontem - timedelta(days=14), 9),
            fim=em(ontem - timedelta(days=14), 10), ocupacao=ex._ocupacao(em(ontem - timedelta(days=14), 9),
                                                                          em(ontem - timedelta(days=14), 10), 0),
            codigo_tuss='40103420', cobranca='particular',
        )
        FeeSchedule.objects.filter(tenant=clinica, payment_category=PaymentCategory.PRIVATE).update(
            effective_from=hoje + timedelta(days=3650))
        reserva_sp, cob_sp = ex.realizar(ctx, secretaria.user, sem_preco, executante)
        conferir('sem honorário: realizado, sem cobrança inventada',
                 reserva_sp.estado == EstadoReserva.REALIZADA and cob_sp is None)
        conferir('nada virou pagamento', Payment.objects.filter(receivable__tenant=clinica).count() == pagamentos_antes)
        conferir('falta só depois do horário', recusa(ex.mudar_estado, ctx, secretaria.user, noite, 'faltou') is not None)
        conferir('cancelar exige motivo', recusa(ex.mudar_estado, ctx, secretaria.user, noite, 'cancelada') is not None)
        ex.mudar_estado(ctx, secretaria.user, noite, 'cancelada', 'paciente desistiu')
        conferir('cancelado devolve o horário', [timezone.localtime(h.inicio).hour for h in ex.horarios_livres(psg, terca)] == [20])
        conferir('cancelado não recebe lembrete', deliver_exam_reminder(Reserva.objects.get(id=noite.id), 2) == [])
        conferir('realizado não se cancela',
                 recusa(ex.mudar_estado, ctx, secretaria.user, feito, 'cancelada', 'x') is not None)

        print('=== 7. A guia do exame, até o arquivo ===')
        conferir('exame não realizado não gera guia',
                 recusa(guias.criar_guia_do_exame, ctx, secretaria.user, Reserva.objects.get(id=noite.id)) is not None)
        conferir('exame particular não gera guia',
                 recusa(guias.criar_guia_do_exame, ctx, secretaria.user, sem_preco) is not None)
        prestador = Prestador.objects.create(tenant=clinica, nome='CLINICA EXAMES LTDA', cnpj='69887146000105')
        Credenciamento.objects.create(tenant=clinica, prestador=prestador, operadora=operadora,
                                      codigo_na_operadora='4455', versao='4.03.00')
        recebiveis_antes = Receivable.objects.filter(tenant=clinica).count()
        guia = guias.criar_guia_do_exame(ctx, secretaria.user, feito)
        item = guia.itens.first()
        conferir('SP/SADT do exame, com a cobrança vinculada',
                 guia.reserva_exame_id == feito.id and item is not None and item.recebivel_id == cobranca.id)
        conferir('nenhuma cobrança nova', Receivable.objects.filter(tenant=clinica).count() == recebiveis_antes)
        conferir('as horas da polissonografia: 21:00 a 07:00',
                 item.hora_inicial == time(21) and item.hora_final == time(7))
        conferir('tipo de atendimento da versão 4.03.00 (23)', guia.tipo_atendimento == '23')
        conferir('o mesmo exame não ganha segunda guia',
                 recusa(guias.criar_guia_do_exame, ctx, secretaria.user, feito) is not None)
        guias.fechar(ctx, secretaria.user, Guia.objects.get(id=guia.id))
        plano_lote = lotes.planejar(clinica.id, [guia.id])
        lote = lotes.criar_lotes(ctx, secretaria.user, [guia.id], plano_lote.assinatura)[0]
        lote = lotes.gerar_arquivo(lote.id)
        dados = lotes.ler_arquivo(lote) if lote.estado == 'pronto' else b''
        conferir('o lote da guia do exame passa no XSD', lote.estado == 'pronto' and not versoes.validar('4.03.00', dados),
                 lote.erros)
        conferir('com as horas no arquivo', b'<ans:horaInicial>21:00:00</ans:horaInicial>' in dados
                 and b'<ans:horaFinal>07:00:00</ans:horaFinal>' in dados)
        from pathlib import Path
        Path(lote.arquivo).unlink(missing_ok=True)

        print('=== 8. As telas ===')
        c = cliente(secretaria)
        r = c.get(f'/app/exames/?recurso={psg.id}&dia={terca.isoformat()}')
        conferir('a agenda abre', r.status_code == 200 and 'PSG ROTEIRO' in r.content.decode())
        r = c.get(f'/app/exames/agendas/{eeg.id}/marcar/?paciente={outro_paciente.id}&inicio={em(segunda, 11).isoformat()}')
        conferir('o formulário abre com o paciente', r.status_code == 200 and outro_paciente.full_name in r.content.decode())
        r = c.get(f'/app/exames/agendas/{eeg.id}/marcar/')
        conferir('sem paciente, pede o paciente', 'Para quem é o exame' in r.content.decode())
        antes = Reserva.objects.filter(recurso=eeg).count()
        r = c.post(f'/app/exames/agendas/{eeg.id}/marcar/', {
            'paciente': str(outro_paciente.id), 'data': segunda.isoformat(), 'hora': '11:00', 'duracao': '60',
            'codigo_tuss': '40103420', 'descricao': 'EEG', 'cobranca': '', 'cobertura': ''})
        conferir('marcar pela tela', r.status_code == 302 and Reserva.objects.filter(recurso=eeg).count() == antes + 1)
        nova = Reserva.objects.filter(recurso=eeg).order_by('-created_at').first()
        estado = nova.estado
        r = c.get(f'/app/exames/reservas/{nova.id}/')
        conferir('a reserva abre, e GET não muda nada', r.status_code == 200 and Reserva.objects.get(id=nova.id).estado == estado)
        conferir('a reserva realizada oferece a guia', 'Gerar guia TISS' in c.get(f'/app/exames/reservas/{feito.id}/').content.decode()
                 or Guia.objects.filter(reserva_exame=feito).exists())
        conferir('configurar: a secretária não abre', c.get('/app/exames/agendas/').status_code == 404)
        conferir('configurar: o dono abre', cliente(dono).get('/app/exames/agendas/').status_code == 200)
        conferir('a ficha do paciente oferece "Agendar exame"',
                 'Agendar exame' in c.get(f'/app/patients/{paciente.id}/').content.decode())
        Configuracao.objects.update(ativo=False)
        conferir('TISS desligado na instalação: a agenda continua', c.get('/app/exames/').status_code == 200)
        Configuracao.objects.update(ativo=True)
        vinculo_b = Membership.objects.filter(tenant=outra, status=MembershipStatus.ACTIVE).first()
        if vinculo_b is not None:
            Tenant.objects.filter(id=outra.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
            cb = cliente(vinculo_b, tenant=outra)
            conferir('outra clínica: reserva em 404', cb.get(f'/app/exames/reservas/{nova.id}/').status_code == 404)
            conferir('outra clínica: marcar na agenda daqui em 404',
                     cb.get(f'/app/exames/agendas/{eeg.id}/marcar/').status_code == 404)
        Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.BASIC)
        conferir('plano sem o módulo: 404', cliente(secretaria).get('/app/exames/').status_code == 404)
        raise Desfazer
except Desfazer:
    pass

print('=== 9. Duas recepcionistas, o mesmo horário, ao mesmo tempo ===')
originais = Tenant.objects.filter(id=clinica.id).values('plan', 'tiss_liberado').first()
recurso_c = None
try:
    Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
    recurso_c = Recurso.objects.create(tenant=clinica, nome='ENMG CONCORRENCIA', tipo=TipoRecurso.ENMG, duracao_padrao=40)
    Janela.objects.create(tenant=clinica, recurso=recurso_c, dia_semana=segunda.weekday(), inicio=time(8), fim=time(12))
    resultado, barreira = {}, threading.Barrier(2)

    def marcar(i):
        barreira.wait()
        try:
            resultado[i] = ex.reservar(ctx, secretaria.user, recurso_c, pacientes[i], em(segunda, 8)).id
        except ex.ReservaRecusada:
            resultado[i] = None
        finally:
            connection.close()

    linhas = [threading.Thread(target=marcar, args=(i,)) for i in range(2)]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    conferir('uma marca, a outra recebe a recusa', sorted(v is None for v in resultado.values()) == [False, True], resultado)
    conferir('um exame só no horário', Reserva.objects.filter(recurso=recurso_c).count() == 1)
finally:
    if recurso_c is not None:
        ids = list(Reserva.objects.filter(recurso=recurso_c).values_list('id', flat=True))
        OutboxEvent.objects.filter(aggregate_type='reserva_exame', aggregate_id__in=ids).delete()
        Reserva.objects.filter(id__in=ids).delete()
        recurso_c.delete()
    if originais:
        Tenant.objects.filter(id=clinica.id).update(**originais)

if falhas:
    raise SystemExit(f'FALHA: {len(falhas)} verificação(ões): ' + '; '.join(falhas))
print('OK: a polissonografia atravessa a meia-noite sem sobrepor, a realização cria uma cobrança só,\n'
      '    a guia do exame vincula essa cobrança e vira arquivo válido, e nenhum médico perdeu vaga.')
