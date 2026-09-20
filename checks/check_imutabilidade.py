"""O que o sistema promete que nao muda, muda mesmo assim?

Cada secao aqui corresponde a uma garantia que estava escrita na
documentacao e **nao** estava garantida no codigo, descobertas numa
revisao externa em 19/09/2026. Um roteiro que so confirmasse o caminho
feliz teria passado em todas elas antes da correcao; por isso cada uma
tenta primeiro o ataque, e so depois confere que o uso legitimo continua
funcionando -- protecao que tambem barra o certo nao e protecao, e
trocaria um defeito por outro.

Tenta quebrar. As perguntas sao:

- da para reescrever atendimento finalizado pela revisao da consulta
  anterior? e pelo admin?
- duas abas gravando ao mesmo tempo perdem texto? e um envio sem versao
  nenhuma passa direto?
- a trilha de auditoria aceita UPDATE ou DELETE vindos da aplicacao?
- a coleta de lixo respeita a guarda de 20 anos, e sabe distinguir anexo
  clinico de administrativo?
- o que a IA le inclui o corpo da consulta em texto livre?
- o chat passa pela politica de privacidade, como os jobs passam?
- tarefa ja enfileirada obedece a revogacao da capacidade clinica?
- cinco tentativas no link do documento sao cinco quando chegam juntas?
"""
import uuid

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django.db import connection, connections, transaction

from accounts.models import User
from clinical import carry_forward as cf
from clinical.models import (
    CarryForwardItem, Encounter, EncounterKind, EncounterStatus, ReviewAction,
)
from patients.models import Patient
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
failures = []
criados = {'encounters': [], 'items': []}


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug=TENANT)
tenant_id = membership.tenant_id
paciente = Patient.objects.filter(tenant_id=tenant_id).first()

client = Client()
client.force_login(user)
sessao = client.session
sessao['tenant_id'] = str(tenant_id)
sessao.save()


def novo_atendimento(status=EncounterStatus.IN_PROGRESS, **campos):
    from django.utils import timezone

    dados = {
        'tenant_id': tenant_id, 'patient': paciente,
        'physician_membership': membership, 'occurred_at': timezone.now(),
        'kind': EncounterKind.STRUCTURED, 'status': status,
    }
    dados.update(campos)
    if status == EncounterStatus.FINALIZED:
        dados.setdefault('finalized_at', timezone.now())
        dados.setdefault('finalized_by', membership)
    encontro = Encounter.objects.create(**dados)
    criados['encounters'].append(encontro.id)
    return encontro


print('=== 1. atendimento finalizado nao se reescreve pela consulta anterior ===')
# O caminho do defeito: o item de copia existe, o atendimento foi
# finalizado depois, e a requisicao antiga e repetida -- aba esquecida
# aberta, clique duplo, botao de voltar.
fechado = novo_atendimento(
    status=EncounterStatus.FINALIZED, plan_text='conduta ASSINADA',
)
item = CarryForwardItem.objects.create(
    tenant_id=tenant_id, target_encounter=fechado, source_encounter=fechado,
    field_path='plan_text', copied_value={'text': 'conduta ANTIGA'},
    source_version_hash=fechado.compute_content_hash(),
    review_action=ReviewAction.PENDING,
)
criados['items'].append(item.id)

resposta = client.post(
    f'/app/clinical/{fechado.id}/carry-forward/{item.id}/review/',
    {'action': 'accepted'}, follow=True,
)
fechado.refresh_from_db()
confere(fechado.plan_text == 'conduta ASSINADA',
        'a view recusa: o texto assinado continua de pe', repr(fechado.plan_text))
confere(fechado.status == EncounterStatus.FINALIZED,
        'o atendimento continua finalizado')

# E o servico, chamado direto -- a view e a porta, nao a garantia.
try:
    cf.review_carry_forward_item(item, 'accepted', membership.id)
    confere(False, 'o servico recusa quando chamado direto', 'aceitou')
except cf.CarryForwardBlocked:
    confere(True, 'o servico recusa quando chamado direto')
fechado.refresh_from_db()
confere(fechado.plan_text == 'conduta ASSINADA',
        'nem por dentro o texto assinado foi trocado')

# O legitimo continua: mesmo item, atendimento aberto.
aberto = novo_atendimento(plan_text='rascunho')
item_ok = CarryForwardItem.objects.create(
    tenant_id=tenant_id, target_encounter=aberto, source_encounter=fechado,
    field_path='plan_text', copied_value={'text': 'conduta trazida'},
    source_version_hash=fechado.compute_content_hash(),
    review_action=ReviewAction.PENDING,
)
criados['items'].append(item_ok.id)
cf.review_carry_forward_item(item_ok, 'accepted', membership.id)
aberto.refresh_from_db()
confere(aberto.plan_text == 'conduta trazida',
        'em atendimento aberto a copia continua funcionando', repr(aberto.plan_text))

print('=== 2. o admin nao oferece formulario para prontuario ===')
from django.contrib import admin as dj_admin

from clinical.models import ClinicalAmendment, EncounterDiagnosis, ExaminationFinding

for modelo in [Encounter, ExaminationFinding, EncounterDiagnosis,
               CarryForwardItem, ClinicalAmendment]:
    registro = dj_admin.site._registry.get(modelo)
    if registro is None:
        confere(False, f'{modelo.__name__}: registrado no admin')
        continue
    pede = type('R', (), {'user': user, 'method': 'GET'})()
    fechado_tudo = (
        not registro.has_add_permission(pede)
        and not registro.has_change_permission(pede)
        and not registro.has_delete_permission(pede)
    )
    confere(fechado_tudo, f'{modelo.__name__}: somente leitura no admin')

print('=== 3. gravar o prontuario e uma operacao so ===')
alvo = novo_atendimento(chief_complaint='original')
url = f'/app/clinical/{alvo.id}/autosave/'

# A view responde conforme quem pergunta: envio normal de formulario
# volta para a tela (302, com a mensagem), e so o `fetch` do autosave
# recebe o codigo de erro. As duas formas sao testadas -- o que importa
# em ambas e que o texto nao muda.
XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

# 3a. Sem a versao: era isto que pulava a conferencia inteira.
resposta = client.post(url, {'chief_complaint': 'sem versao'})
alvo.refresh_from_db()
confere(alvo.chief_complaint == 'original',
        'envio sem row_version nao grava', f'HTTP {resposta.status_code}')
resposta = client.post(url, {'chief_complaint': 'sem versao'}, **XHR)
alvo.refresh_from_db()
confere(resposta.status_code == 400 and alvo.chief_complaint == 'original',
        'e o autosave recebe 400', f'HTTP {resposta.status_code}')

# 3b. Versao velha: a segunda aba nao apaga a primeira.
versao = alvo.row_version
client.post(url, {'chief_complaint': 'primeira aba', 'row_version': str(versao)})
alvo.refresh_from_db()
depois_da_primeira = alvo.chief_complaint
resposta = client.post(
    url, {'chief_complaint': 'segunda aba', 'row_version': str(versao)}, **XHR,
)
alvo.refresh_from_db()
confere(resposta.status_code == 409 and alvo.chief_complaint == depois_da_primeira,
        'a segunda aba com versao velha e recusada (409)', f'HTTP {resposta.status_code}')
confere(depois_da_primeira == 'primeira aba',
        'o que a primeira aba gravou continua la', repr(alvo.chief_complaint))

# 3c. Versao correta grava e devolve a nova.
resposta = client.post(
    url, {'chief_complaint': 'com a versao certa', 'row_version': str(alvo.row_version)},
)
alvo.refresh_from_db()
confere(alvo.chief_complaint == 'com a versao certa',
        'com a versao certa o salvamento funciona')

# 3d. Finalizado no meio do caminho.
alvo.status = EncounterStatus.FINALIZED
from django.utils import timezone

alvo.finalized_at = timezone.now()
alvo.finalized_by = membership
alvo.save(update_fields=['status', 'finalized_at', 'finalized_by'])
resposta = client.post(
    url, {'chief_complaint': 'depois de fechar', 'row_version': str(alvo.row_version)}, **XHR,
)
alvo.refresh_from_db()
confere(resposta.status_code == 409 and alvo.chief_complaint == 'com a versao certa',
        'salvamento em atendimento finalizado e recusado (409)',
        f'HTTP {resposta.status_code}')

print('=== 4. a trilha de auditoria nao aceita ser reescrita ===')
from audit.models import AuditEvent
from audit.services import record_audit_event

evento = record_audit_event(user, tenant_id, 'checks.imutabilidade', outcome='success')
confere(AuditEvent.objects.filter(id=evento.id).exists(), 'inserir na trilha continua funcionando')

for operacao, acao in [
    ('UPDATE', lambda: AuditEvent.objects.filter(id=evento.id).update(action='adulterado')),
    ('DELETE', lambda: AuditEvent.objects.filter(id=evento.id).delete()),
]:
    try:
        # Transacao propria: o erro do banco aborta a transacao corrente, e
        # sem isolar isto o resto do roteiro morreria junto.
        with transaction.atomic():
            acao()
        confere(False, f'{operacao} na trilha e recusado', 'passou')
    except Exception as exc:                                  # noqa: BLE001
        confere(True, f'{operacao} na trilha e recusado', type(exc).__name__)

evento.refresh_from_db()
confere(evento.action == 'checks.imutabilidade', 'a linha continua com o conteudo original')

print('=== 5. a coleta de lixo respeita a guarda de 20 anos ===')
from documents.models import Attachment, AttachmentClassification
from documents.retention import RETENTION_YEARS, eliminacao_permitida, retention_expires_at

prazo = retention_expires_at(paciente)
confere(prazo is not None, 'paciente com prontuario tem prazo de guarda', str(prazo)[:10] if prazo else '')
if prazo is not None:
    from documents.retention import last_record_at

    anos = (prazo - last_record_at(paciente)).days / 365.25
    confere(19.9 < anos < 20.1, f'o prazo e de {RETENTION_YEARS} anos de calendario',
            f'{anos:.2f} anos')

confere(not eliminacao_permitida(paciente, AttachmentClassification.CLINICAL),
        'anexo CLINICO dentro da guarda nao pode ser eliminado')
confere(eliminacao_permitida(paciente, AttachmentClassification.ADMINISTRATIVE),
        'anexo ADMINISTRATIVO nao carrega a guarda do prontuario')

print('=== 6. a IA le o corpo da consulta em texto livre ===')
from ai.context import build_ai_authorization
from ai.tools.clinical import get_patient_timeline

livre = novo_atendimento(
    kind=EncounterKind.FREE_TEXT,
    free_text='CORPO DA CONSULTA EM TEXTO LIVRE',
    impressions='IMPRESSAO DO MEDICO',
)
contexto = type('C', (), {
    'tenant_id': tenant_id, 'user_id': user.id, 'membership_id': membership.id,
})()
autorizacao = build_ai_authorization(contexto, patient_id=paciente.id)
linha = get_patient_timeline(autorizacao, limit=20)
achado = next((e for e in linha if str(e['encounter_id']) == str(livre.id)), None)
confere(achado is not None, 'o atendimento em texto livre aparece na linha do tempo')
if achado:
    confere(achado.get('free_text') == 'CORPO DA CONSULTA EM TEXTO LIVRE',
            'o corpo da consulta chega a IA')
    confere(achado.get('impressions') == 'IMPRESSAO DO MEDICO',
            'as impressoes chegam a IA')

from ai.chat_prompt import build_patient_context

bloco = build_patient_context(autorizacao)
confere('CORPO DA CONSULTA' in bloco or '[PACIENTE]' in bloco,
        'o texto livre entra no contexto montado para o chat')

print('=== 7. o chat passa pela mesma politica dos jobs ===')
from ai import privacy_policy
from ai.tasks import _avaliar_privacidade

sessao_falsa = type('S', (), {'tenant_id': tenant_id, 'patient_id': paciente.id})()
mensagem = type('M', (), {'content': 'texto sem marcador nenhum'})()
decisao = _avaliar_privacidade(sessao_falsa, [mensagem])
confere(decisao.allowed, 'conversa comum passa')

marcador = privacy_policy.RARE_DISEASE_MARKERS[0]
suspeita = type('M', (), {'content': f'paciente com {marcador} na familia'})()
decisao = _avaliar_privacidade(sessao_falsa, [suspeita])
confere(not decisao.allowed, 'conversa com marcador de risco e bloqueada', decisao.reason[:60])

print('=== 8. tarefa enfileirada obedece a revogacao da capacidade ===')
from ai.context import AIAuthorizationDenied
from ai.tasks import _membership_id_of
from tenancy.models import Role

sessao_ia = type('S', (), {
    'tenant_id': tenant_id, 'owner_user_id': user.id, 'patient_id': paciente.id,
})()
confere(_membership_id_of(sessao_ia) == membership.id,
        'com o papel medico, a tarefa segue')

papeis_originais = list(membership.roles)
try:
    membership.roles = [Role.SECRETARY]
    membership.save(update_fields=['roles'])
    try:
        _membership_id_of(sessao_ia)
        confere(False, 'sem o papel medico a tarefa e recusada', 'seguiu assim mesmo')
    except AIAuthorizationDenied as exc:
        confere(True, 'sem o papel medico a tarefa e recusada', str(exc)[:50])
finally:
    membership.roles = papeis_originais
    membership.save(update_fields=['roles'])
    confere(_membership_id_of(sessao_ia) == membership.id,
            'devolvido o papel, a tarefa volta a seguir')

print('=== 9. cinco tentativas sao cinco, mesmo chegando juntas ===')
from django.utils import timezone

from communications.access import MAX_ATTEMPTS, AccessDenied, AccessLocked, verify_identity
from communications.models import DocumentAccessToken
from documents.models import MedicalDocument, MedicalDocumentKind
from patients.models import PatientContact

documento = MedicalDocument.objects.filter(tenant_id=tenant_id).first()
descartar_documento = False
if documento is None:
    documento = MedicalDocument.objects.create(
        tenant_id=tenant_id, patient=paciente, physician=membership,
        kind=MedicalDocumentKind.values[0],
    )
    descartar_documento = True

contato = PatientContact.objects.filter(tenant_id=tenant_id, patient=paciente).first()
descartar_contato = False
if contato is None:
    contato = PatientContact.objects.create(
        tenant_id=tenant_id, patient=paciente, phone='11999990000',
    )
    descartar_contato = True

token = DocumentAccessToken.objects.create(
    tenant_id=tenant_id, document=documento, contact=contato,
    token_hash=uuid.uuid4().hex * 2, otp_attempts=0,
    expires_at=timezone.now() + timezone.timedelta(days=30),
)

# Duas requisicoes que **leram o token antes** de qualquer uma gravar --
# e exatamente esta a corrida, e e por isso que o teste carrega duas
# instancias separadas em vez de reusar a mesma. Com o incremento feito em
# Python (`token.otp_attempts += 1; save()`) as duas partiam de zero e
# gravavam um: duas tentativas contadas como uma, e cinco viravam quantas
# o atacante quisesse. Com `UPDATE ... otp_attempts + 1` quem soma e o
# banco, e a instancia velha nao apaga a contagem da outra.
primeira = DocumentAccessToken.objects.get(pk=token.pk)
segunda = DocumentAccessToken.objects.get(pk=token.pk)
for instancia in (primeira, segunda):
    try:
        verify_identity(instancia, '0000')
    except (AccessDenied, AccessLocked):
        pass
token.refresh_from_db()
confere(token.otp_attempts == 2,
        'duas tentativas simultaneas contam duas', f'contou {token.otp_attempts}')

# E o limite trava de verdade.
DocumentAccessToken.objects.filter(pk=token.pk).update(otp_attempts=MAX_ATTEMPTS)
token.refresh_from_db()
try:
    verify_identity(token, '0000')
    confere(False, 'no limite, o link trava', 'aceitou mais uma')
except AccessLocked:
    confere(True, 'no limite, o link trava')
token.refresh_from_db()
confere(token.otp_attempts == MAX_ATTEMPTS,
        'o contador nao passa do limite', str(token.otp_attempts))

token.delete()
if descartar_contato:
    contato.delete()
if descartar_documento:
    documento.delete()

print('=== limpeza ===')
CarryForwardItem.objects.filter(id__in=criados['items']).delete()
removidos = Encounter.objects.filter(id__in=criados['encounters']).delete()
print(f'  atendimentos do roteiro removidos: {criados["encounters"].__len__()}')
print('  (o evento de auditoria criado na secao 4 fica -- a trilha nao se apaga)')

print()
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o que o sistema promete que nao muda, nao muda -- e o uso legitimo continua passando.')
