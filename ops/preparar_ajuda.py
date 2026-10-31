"""Deixa a Clínica Demo A no estado que as capturas do manual descrevem.

Roda **só no ambiente local**, antes de `ops/capturar_ajuda.py`:

    docker compose exec -T app python manage.py shell < ops/preparar_ajuda.py

e `scripts/capturar_ajuda.sh` já o chama.

**Por que existe.** O banco de demonstração (`seed_demo`) nasceu antes do
TISS, da agenda de exames e do SNCR: as telas desses módulos abriam vazias,
e captura de tela vazia não ensina nada — foi por isso que os quatro artigos
ficaram sem imagem. Escrever os dados à mão a cada rodada é o mesmo erro
das capturas manuais de setembro: um dia esquece-se um passo e o manual
publica outra coisa. Aqui o estado é declarado uma vez, e repetir não
duplica nada (cada objeto é procurado pelo nome antes de criado).

**Nada aqui é real, e não pode ser** — o manual é público:

- a operadora é a **Operadora Demo Saúde**, registro ANS 999001 (nenhuma
  operadora real tem esse número), e não uma marca real: um print com o
  nome de uma operadora de verdade sugeriria integração homologada com ela;
- o **bloco SNCR é fictício** (`2610.6-35.000000001` a `...001000`) e fica
  no médico da demonstração. O bloco verdadeiro do responsável vive só em
  produção e não aparece em captura nenhuma;
- os pacientes são os da semeadura, mais três sintéticos.

Recusa rodar fora do ambiente local (`RELEASE_ID` de produção é o SHA do
commit): o script liga chaves da instalação, e ligá-las em produção sem
querer seria exatamente o acidente que as chaves existem para impedir.
"""
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

if settings.RELEASE_ID != 'dev':
    raise SystemExit('preparar_ajuda: só roda no ambiente local (RELEASE_ID=dev).')

from accounts.models import PhysicianProfile
from agenda_exames import services as exames
from agenda_exames.models import Janela, Recurso, Reserva, TipoRecurso
from catalogs.models import CatalogRelease, CatalogReleaseStatus, CatalogSystem, ProcedureCode
from finance.models import FeeSchedule, PaymentCategory, Receivable
from patients.models import HealthPlan, HealthPlanKind, Insurer, Patient, PatientCoverage, SexAtRegistration
from scheduling import services as agenda
from scheduling.models import Appointment, AppointmentType, BillingMode
from sncr import numeracao
from sncr.models import Ambiente, BlocoNumeracao, Configuracao as ConfigSncr, EstadoPedido, PedidoNumeracao
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import capabilities_for
from tenancy.plans import PlanCode
from tiss import guias
from tiss.models import Configuracao as ConfigTiss, Credenciamento, EstadoGuia, Guia, Prestador, ProfissionalTiss, TipoGuia

clinica = Tenant.objects.get(slug='demo-clinica-a')
vinculos = list(Membership.objects.filter(tenant=clinica, status=MembershipStatus.ACTIVE).select_related('user'))
dona = next(m for m in vinculos if m.user.email == 'doctor-a@demo.neurodoc.local')
secretaria = next(m for m in vinculos if m.user.email == 'secretary-a@demo.neurodoc.local')
hoje = timezone.localdate()
agora = timezone.now()


def contexto(quem):
    return AccessContext(
        user_id=quem.user_id, tenant_id=clinica.id, membership_id=quem.id,
        permissions=frozenset(quem.roles), request_id=uuid.uuid4(),
        capabilities=capabilities_for(quem.roles, clinically_enabled=quem.can_practice_clinically(),
                                      ai_contracted=True, tiss_contracted=True),
    )


ctx_dona, ctx_sec = contexto(dona), contexto(secretaria)


def momento(dia, hh, mm=0):
    return timezone.make_aware(datetime.combine(dia, time(hh, mm)))


# ------------------------------------------------------------ chaves
Tenant.objects.filter(id=clinica.id).update(plan=PlanCode.COMPLETE, tiss_liberado=True)
ConfigTiss.objects.filter(id=ConfigTiss.carregar().id).update(ativo=True)
cfg = ConfigSncr.carregar()
ConfigSncr.objects.filter(id=cfg.id).update(ativo=True, ambiente=Ambiente.PRODUCAO, cnpj_mantenedora='69887146000105')
print('chaves: TISS ligado e liberado, SNCR ligado (produção, só local)')

# ------------------------------------------------------- pacientes extras
for nome, nasc, sexo, cidade in (
    ('Helena Ribeiro Demonstração', date(1958, 2, 14), SexAtRegistration.FEMALE, 'Campinas'),
    ('Marcos Teixeira Exemplo', date(1972, 9, 3), SexAtRegistration.MALE, 'São Paulo'),
    ('Luiza Fernandes Fictícia', date(1991, 11, 22), SexAtRegistration.FEMALE, 'Santos'),
):
    Patient.objects.get_or_create(
        tenant=clinica, full_name=nome.upper(),
        defaults={'birth_date': nasc, 'sex_at_registration': sexo, 'city': cidade, 'state': 'SP',
                  'responsible_membership': dona},
    )
carlos = Patient.objects.get(tenant=clinica, full_name='CARLOS ADULTO DA SILVA')
helena = Patient.objects.get(tenant=clinica, full_name='HELENA RIBEIRO DEMONSTRAÇÃO')
marcos = Patient.objects.get(tenant=clinica, full_name='MARCOS TEIXEIRA EXEMPLO')

# ---------------------------------------------------------------- SNCR
perfil = PhysicianProfile.objects.get(user=dona.user)
if not BlocoNumeracao.objects.filter(medico=perfil, inicio='2610.6-35.000000001').exists():
    pedido = PedidoNumeracao.objects.create(
        medico=perfil, solicitado_por=dona.user, tenant=clinica, tipo='RCE', ambiente=Ambiente.PRODUCAO,
        uf=perfil.crm_state, documento=perfil.crm_number, cnpj='69887146000105',
        estado=EstadoPedido.CONCLUIDO, enviado_em=agora, concluido_em=agora,
        mensagem='Bloco 2610.6-35.000000001 a 2610.6-35.000001000 recebido.',
    )
    numeracao.registrar_bloco(pedido, {'inicio': '2610.6-35.000000001', 'fim': '2610.6-35.000001000',
                                       'quantidade': 1000})
print('SNCR: bloco fictício de RCE com', numeracao.saldo(perfil, 'RCE', Ambiente.PRODUCAO), 'números livres')

# ----------------------------------------------------------- convênio TISS
operadora, _ = Insurer.objects.get_or_create(tenant=clinica, name='Operadora Demo Saúde',
                                             defaults={'ans_registration': '999001'})
plano, _ = HealthPlan.objects.get_or_create(tenant=clinica, insurer=operadora, name='Demo Saúde Ambulatorial',
                                            defaults={'kind': HealthPlanKind.AMBULATORIAL})
coberturas = {}
for paciente, carteira in ((carlos, '0099887766554433'), (helena, '0011223344556677'), (marcos, 'A7257000281000')):
    coberturas[paciente.id] = PatientCoverage.objects.get_or_create(
        tenant=clinica, patient=paciente, plan=plano,
        defaults={'member_number': carteira, 'starts_on': date(2024, 1, 1)},
    )[0]

prestador, _ = Prestador.objects.get_or_create(
    tenant=clinica, nome='CLINICA DEMO A NEUROLOGIA LTDA', defaults={'cnpj': clinica.cnpj, 'cnes': '1234567'},
)
credenciamento, _ = Credenciamento.objects.get_or_create(
    tenant=clinica, prestador=prestador, operadora=operadora,
    defaults={'codigo_na_operadora': '00012345', 'versao': '4.03.00',
              'portal_url': 'https://portal.exemplo.invalid/prestador'},
)
ana, _ = ProfissionalTiss.objects.get_or_create(
    tenant=clinica, numero_conselho=perfil.crm_number, uf=perfil.crm_state,
    defaults={'nome': 'DRA. ANA NEURO', 'cbo': '225112', 'membership': dona},
)
externo, _ = ProfissionalTiss.objects.get_or_create(
    tenant=clinica, numero_conselho='98765', uf='SP',
    defaults={'nome': 'DR. JOSÉ EXEMPLO (SOLICITANTE)', 'cbo': '225125'},
)

tuss = CatalogRelease.objects.filter(system=CatalogSystem.TUSS, status=CatalogReleaseStatus.ACTIVE).first()
codigos = {c: ProcedureCode.objects.filter(release=tuss, code=c).first() for c in
           ('10101012', '40103170', '40103323', '40103528')}
for codigo, valor in (('10101012', '180.00'), ('40103170', '220.00'), ('40103323', '310.93'), ('40103528', '650.00')):
    FeeSchedule.objects.get_or_create(
        tenant=clinica, physician=None, plan=plano, procedure=codigos[codigo], appointment_type=None,
        payment_category=PaymentCategory.INSURANCE,
        defaults={'gross_amount': Decimal(valor), 'doctor_share_amount': Decimal('0'),
                  'effective_from': date(2024, 1, 1)},
    )
FeeSchedule.objects.get_or_create(
    tenant=clinica, physician=None, plan=plano, procedure=None, appointment_type=AppointmentType.FOLLOW_UP,
    payment_category=PaymentCategory.INSURANCE,
    defaults={'gross_amount': Decimal('180.00'), 'doctor_share_amount': Decimal('0'), 'effective_from': date(2024, 1, 1)},
)
print('TISS: operadora, plano, prestador, credenciamento 4.03.00, dois profissionais, tabela de honorários')

# ------------------------------------------------------ agendas de exame
recursos = {}
for nome, tipo, duracao, codigo, desc, janelas in (
    ('EEG — sala 1', TipoRecurso.EEG, 40, '40103170', 'EEG de rotina',
     [(d, time(8), time(18)) for d in range(5)]),
    ('ENMG — sala 2', TipoRecurso.ENMG, 60, '40103323', 'Eletroneuromiografia de MMSS',
     [(d, time(8), time(17)) for d in range(5)]),
    ('Polissonografia — leito 1', TipoRecurso.PSG, 600, '40103528', 'Polissonografia de noite inteira (PSG)',
     [(d, time(20), time(7)) for d in range(7)]),
):
    recurso, criado = Recurso.objects.get_or_create(
        tenant=clinica, nome=nome,
        defaults={'tipo': tipo, 'duracao_padrao': duracao, 'codigo_tuss': codigo, 'descricao_tuss': desc,
                  'executante_padrao': ana},
    )
    if criado:
        for dia, ini, fim in janelas:
            Janela.objects.create(tenant=clinica, recurso=recurso, dia_semana=dia, inicio=ini, fim=fim)
    recursos[tipo] = recurso


def reservar(recurso, paciente, inicio, **extra):
    existente = Reserva.objects.filter(recurso=recurso, paciente=paciente, inicio=inicio).first()
    if existente:
        return existente
    return exames.reservar(ctx_sec, secretaria.user, recurso, paciente, inicio, encaixe=True,
                           motivo_encaixe='demonstração do manual', **extra)


# A ENMG que já aconteceu hoje: realizada, com cobrança e guia SP/SADT.
# O serviço recusa marcar no passado — com razão —, então a reserva nasce
# na semana que vem e é recuada para esta manhã direto no banco local.
enmg = Reserva.objects.filter(recurso=recursos[TipoRecurso.ENMG], paciente=carlos, inicio__date__lte=hoje).first()
if enmg is None:
    enmg = reservar(recursos[TipoRecurso.ENMG], carlos, momento(hoje + timedelta(days=7), 8),
                    solicitante=externo, cobranca='convenio', cobertura=coberturas[carlos.id])
    inicio_enmg = agora.replace(second=0, microsecond=0) - timedelta(hours=3)
    Reserva.objects.filter(id=enmg.id).update(
        inicio=inicio_enmg, fim=inicio_enmg + timedelta(minutes=60),
        ocupacao=exames._ocupacao(inicio_enmg, inicio_enmg + timedelta(minutes=60), 0),
    )
    enmg.refresh_from_db()
if enmg.estado != 'realizada':
    exames.realizar(ctx_sec, secretaria.user, enmg, ana)
# Os exames de hoje e de amanhã na agenda, e a polissonografia de hoje à noite.
# Depois das 20h a polissonografia vai para a noite seguinte: o serviço
# não marca no passado, e a captura roda a qualquer hora.
noite = hoje if timezone.localtime(agora).hour < 20 else hoje + timedelta(days=1)
for recurso, paciente, inicio in (
    (recursos[TipoRecurso.EEG], helena, momento(hoje + timedelta(days=1), 9)),
    (recursos[TipoRecurso.EEG], marcos, momento(hoje + timedelta(days=1), 10, 20)),
    (recursos[TipoRecurso.ENMG], helena, momento(hoje + timedelta(days=1), 14)),
    (recursos[TipoRecurso.PSG], marcos, momento(noite, 21)),
):
    reservar(recurso, paciente, inicio, solicitante=externo, cobranca='convenio',
             cobertura=coberturas[paciente.id])
print('agenda de exames: EEG, ENMG e PSG, com a ENMG de hoje realizada e a PSG de hoje à noite')

# ----------------------------------------------------------------- guias
def fechada(guia):
    guia.refresh_from_db()
    if guia.estado == EstadoGuia.RASCUNHO:
        faltando = [p.campo for p in guias.pendencias(guia) if p.impede]
        if faltando:
            print('  guia', guia.numero_prestador, 'ainda com pendência:', faltando)
            return guia
        guias.fechar(ctx_sec, secretaria.user, guia)
        guia.refresh_from_db()
    return guia


# 1. A SP/SADT da ENMG realizada.
g_exame = Guia.objects.filter(tenant=clinica, reserva_exame=enmg).exclude(estado=EstadoGuia.CANCELADA).first()
if g_exame is None:
    g_exame = guias.criar_guia_do_exame(ctx_sec, secretaria.user, enmg)
    guias.registrar_indicacao(ctx_dona, dona.user, g_exame, 'Parestesias em mãos há seis meses.')
    Guia.objects.filter(id=g_exame.id).update(senha='AO6426648', data_autorizacao=hoje)
fechada(g_exame)

# 2. A consulta de convênio de hoje, com check-in: Consulta vinculada à cobrança.
# Ontem, e não hoje: os roteiros contam com a agenda de hoje da médica da
# demonstração vazia (`check_intervalos_e_ficha` apaga a grade publicada
# hoje só quando não há consulta no dia), e o preparo não pode mudar o que
# eles encontram.
appt = Appointment.objects.filter(tenant=clinica, patient=helena, physician_membership=dona).first()
if appt is not None and timezone.localtime(appt.starts_at).date() >= hoje:
    ontem = appt.starts_at - timedelta(days=1)
    from psycopg.types.range import Range as _Faixa

    fim = appt.ends_at - timedelta(days=1)
    Appointment.objects.filter(id=appt.id).update(starts_at=ontem, ends_at=fim,
                                                   occupied_range=_Faixa(ontem, fim, '[)'))
    appt.refresh_from_db()
if appt is None:
    ini = momento(hoje - timedelta(days=1), 10)
    appt = agenda.reserve_appointment(ctx_sec, helena, dona, ini, ini + timedelta(minutes=30),
                                      AppointmentType.FOLLOW_UP, is_overbook=True,
                                      override_reason='demonstração do manual', override_by=dona)
    agenda.set_billing_mode(ctx_sec, appt, BillingMode.INSURANCE, coberturas[helena.id].id, secretaria.user_id)
    agenda.check_in(appt, secretaria.user_id)
g_consulta = Guia.objects.filter(tenant=clinica, appointment=appt).exclude(estado=EstadoGuia.CANCELADA).first()
if g_consulta is None:
    g_consulta = guias.criar_guia(ctx_sec, secretaria.user, helena, TipoGuia.CONSULTA, appointment=appt)
    if not g_consulta.itens.exclude(codigo='').exists():
        guias.gravar_item(ctx_sec, secretaria.user, g_consulta,
                          {'data_execucao': timezone.localtime(appt.starts_at).date(), 'codigo': '10101012',
                           'tabela': '22'})
fechada(g_consulta)

# 3. Uma SP/SADT em preenchimento, com pendências à vista — a tela do artigo.
g_rascunho = Guia.objects.filter(tenant=clinica, paciente=marcos, tipo=TipoGuia.SP_SADT,
                                 estado=EstadoGuia.RASCUNHO).first()
if g_rascunho is None:
    g_rascunho = guias.criar_guia(ctx_sec, secretaria.user, marcos, TipoGuia.SP_SADT)
    guias.gravar_item(ctx_sec, secretaria.user, g_rascunho,
                      {'data_execucao': hoje, 'codigo': '40103170', 'tabela': '22'})
print('guias:', g_exame.numero_prestador, g_exame.get_estado_display(), '|', g_consulta.numero_prestador,
      g_consulta.get_estado_display(), '|', g_rascunho.numero_prestador, g_rascunho.get_estado_display())

# ------------------------------------------- documento, portal e chat
# Até aqui a demonstração não tinha documento emitido, pedido do portal nem
# conversa: as capturas de setembro mostravam um rascunho de "Teste
# Permissao Secretaria" no lugar da entrega e uma fila vazia no lugar da
# fila. A assinatura digital exige certificado ICP-Brasil, que a
# demonstração não tem; o relatório é emitido em papel e marcado como
# emitido direto no banco local, só para a tela de entrega existir.
from ai.chat_models import ChatMessage, ChatMessageRole, ChatSession
from communications.models import Delivery, DeliveryChannel
from documents import issuance
from documents.models import DocumentRequest, DocumentRequestKind, MedicalDocument, MedicalDocumentStatus
from tenancy.models import ClinicProfile

ClinicProfile.objects.filter(tenant=clinica).update(patient_portal_enabled=True)

# A semeadura antiga gravava "self", e a tela de entrega mostrava "(self)";
# o produto grava "Próprio paciente" (`patients.contacts`).
from patients.contacts import SELF_RELATIONSHIP

carlos.contacts.filter(relationship='self').update(relationship=SELF_RELATIONSHIP)
contato = carlos.contacts.filter(relationship=SELF_RELATIONSHIP).first()
if contato and not contato.email:
    type(contato).objects.filter(id=contato.id).update(email='carlos.demo@exemplo.invalid')
    contato.refresh_from_db()
documento = MedicalDocument.objects.filter(tenant=clinica, patient=carlos, kind='report').first()
if documento is None:
    documento = issuance.create_draft(
        clinica, carlos, None, dona, dona.user_id, 'report',
        {'report_text': 'Paciente em acompanhamento neurológico regular, com crises controladas desde o último ajuste.'},
    )
    documento = issuance.issue_on_paper(documento, dona.user_id)
    MedicalDocument.objects.filter(id=documento.id).update(status=MedicalDocumentStatus.ISSUED)
    documento.refresh_from_db()
if contato and not Delivery.objects.filter(document=documento).exists():
    for canal in (DeliveryChannel.EMAIL, DeliveryChannel.SMS):
        Delivery.objects.create(tenant=clinica, document=documento, contact=contato, channel=canal,
                                event_version=1, status='delivered',
                                idempotency_key=f'ajuda-{documento.id}-{canal}')

if not DocumentRequest.objects.filter(tenant=clinica, patient=helena).exists():
    DocumentRequest.objects.create(
        tenant=clinica, patient=helena, kind=DocumentRequestKind.PRESCRIPTION_SIMPLE,
        requester_name='HELENA RIBEIRO DEMONSTRAÇÃO', requester_is_patient=True,
        payload={'medicacoes': [{'nome': 'Levetiracetam 500 mg', 'posologia': '1 comprimido de 12 em 12 horas'}],
                 'observacao': 'Meu remédio acaba na semana que vem.'},
        privacy_ack_at=agora, privacy_notice_version='2026-09-v1',
    )

if not ChatSession.objects.filter(tenant=clinica, patient=carlos).exists():
    sessao = ChatSession.objects.create(tenant=clinica, owner_user=dona.user, patient=carlos,
                                        title='Resumo do caso para o retorno', last_message_at=agora)
    ChatMessage.objects.create(tenant=clinica, session=sessao, role=ChatMessageRole.USER, sequence=1,
                               content='Resuma a evolução deste paciente para o retorno de hoje.')
    ChatMessage.objects.create(
        tenant=clinica, session=sessao, role=ChatMessageRole.ASSISTANT, sequence=2,
        content=('**Evolução registrada**\n\n'
                 '- Dois atendimentos finalizados, ambos com crises controladas.\n'
                 '- Última conduta: manter o esquema atual e reavaliar em seis meses.\n\n'
                 'Não encontrei exames de imagem registrados no prontuário deste paciente.\n\n'
                 '*Revise antes de usar — isto é material de apoio, não conduta.*'),
    )
print('documento emitido com duas entregas, um pedido no portal e uma conversa de chat')

# Ids que o roteiro de captura usa para chegar às telas sem procurar na lista.
import json
import os

# O atendimento em aberto das capturas do prontuário, e a chave TOTP da
# dona da demonstração: a área TISS pede o segundo fator de novo, e o
# navegador da captura precisa responder sozinho. Só a da demonstração,
# local — nunca de conta real.
from clinical.models import Encounter
from django_otp.plugins.otp_totp.models import TOTPDevice

aberto = Encounter.objects.filter(tenant=clinica, patient=carlos, kind='structured', status='draft').first()
if aberto is None:
    from clinical import carry_forward as cf

    aberto = Encounter.objects.create(
        tenant=clinica, patient=carlos, physician_membership=dona, occurred_at=agora, status='draft',
        kind='structured', chief_complaint='Retorno: crises controladas, sem efeitos adversos.',
        hpi='Sem crises desde o último ajuste. Dorme bem, sem sonolência diurna. Adesão regular ao tratamento.',
    )
    origem = cf.default_source_encounter(aberto)
    if origem is not None:
        cf.carry_forward(ctx_dona, aberto, origem)
dispositivo = TOTPDevice.objects.filter(user=dona.user, confirmed=True).first()
if dispositivo:
    # Os roteiros de MFA erram o código de propósito, e o django-otp passa a
    # esperar cada vez mais entre tentativas: a captura receberia "Código
    # inválido" com o código certo. Zera a espera, só deste dispositivo local.
    TOTPDevice.objects.filter(id=dispositivo.id).update(throttling_failure_count=0,
                                                         throttling_failure_timestamp=None)
ids = {
    'atendimento': str(aberto.id) if aberto else '',
    'totp': dispositivo.key if dispositivo else '',
    'guia_rascunho': str(g_rascunho.id), 'guia_exame': str(g_exame.id),
    'reserva_enmg': str(enmg.id), 'psg': str(recursos[TipoRecurso.PSG].id),
    'documento': str(documento.id), 'token': documento.validation_token,
    'carlos': str(carlos.id), 'slug': clinica.slug, 'noite': noite.isoformat(),
    'segunda': (hoje + timedelta(days=7 - hoje.weekday())).isoformat(),
    'chat': str(ChatSession.objects.filter(tenant=clinica, patient=carlos).first().id),
}
print('IDS ' + json.dumps(ids))
