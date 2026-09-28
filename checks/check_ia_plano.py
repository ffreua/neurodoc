"""A IA e do plano que a contratou -- e so dele?

Tenta quebrar. As perguntas sao:

- o catalogo e a pagina de vendas concordam sobre quem tem IA?
- um medico verificado, num plano sem IA, ainda recebe `CLINICAL_AI`?
- da para chamar `capabilities_for` sem decidir o plano?
- a tela do chat abre pela URL direta, sem passar pelo menu?
- o link some da barra lateral, ou fica dando 404 na cara de quem clica?
- `build_ai_authorization` recusa? e o resumo automatico, que nasce de um
  evento e nao passa por tela nenhuma?
- esse resumo recusado **levanta**? (se levantar, o despachante reentrega
  com recuo e marca o evento como FAILED -- falha falsa a cada
  atendimento finalizado)
- rebaixar entre enfileirar e executar ainda impede a chamada externa?
- a tela de configuracao some, ou explica qual plano tem o recurso?
- e ela deixa gravar uma chave de provedor que nunca vai rodar?
"""
import atexit
import uuid
from types import SimpleNamespace

from django.conf import settings as dj_settings
from django.test import Client
from django.test.utils import override_settings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from ai.context import AIAuthorizationDenied, build_ai_authorization
from ai.graphs import PROMPT_VERSION, build_prompt
from ai.handlers import handle_encounter_finalized
from ai.models import AIJob
from clinical.models import Encounter, EncounterStatus
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Role, Tenant
from tenancy.permissions import Capability, capabilities_for
from tenancy.plans import PLANS, PlanCode, has_clinical_ai

falhas = []

clinica = Tenant.objects.get(slug='demo-clinica-a')


def _tem(vinculo, capacidade):
    return capacidade in capabilities_for(
        vinculo.roles, clinically_enabled=vinculo.can_practice_clinically(),
        ai_contracted=True,
    )


_vinculos = list(
    Membership.objects
    .filter(tenant=clinica, status=MembershipStatus.ACTIVE)
    .select_related('user')
)
# Tres vinculos diferentes, porque tres perguntas diferentes. Pegar "o
# primeiro medico" para tudo foi o que escondeu um defeito: o medico sem
# papel administrativo nao alcanca a tela de configuracao, e usar so ele
# fazia a secao da tela testar o 404 da capacidade, achando que testava o
# do plano.
medico = next((m for m in _vinculos if Role.DOCTOR in (m.roles or [])), None)
gestor = next((m for m in _vinculos if _tem(m, Capability.MANAGE_INTEGRATIONS)), None)
sem_admin = next(
    (m for m in _vinculos
     if Role.DOCTOR in (m.roles or []) and not _tem(m, Capability.MANAGE_INTEGRATIONS)),
    None,
)
if None in (medico, gestor, sem_admin):
    print('  (demonstracao incompleta; roteiro pulado)')
    raise SystemExit(0)
print(f'  medico={medico.user.email}  gestor={gestor.user.email}  '
      f'sem_admin={sem_admin.user.email}')

# O plano da clinica de demonstracao e restaurado aconteca o que acontecer.
# Sem isto, um roteiro interrompido no meio deixa a demonstracao rebaixada
# e os proximos roteiros falham por um motivo que nao e o deles.
_plano_original = clinica.plan
_settings_original = dict(clinica.settings or {})


@atexit.register
def restaurar():
    Tenant.objects.filter(id=clinica.id).update(
        plan=_plano_original, settings=_settings_original,
    )


def com_plano(codigo):
    Tenant.objects.filter(id=clinica.id).update(plan=codigo)
    clinica.refresh_from_db()


def capacidades(quem=None):
    vinculo = Membership.objects.select_related('tenant').get(id=(quem or medico).id)
    return capabilities_for(
        vinculo.roles,
        clinically_enabled=vinculo.can_practice_clinically(),
        ai_contracted=has_clinical_ai(vinculo.tenant.plan),
    )


def contexto(quem=None):
    quem = quem or medico
    return AccessContext(
        user_id=quem.user_id, tenant_id=clinica.id, membership_id=quem.id,
        permissions=frozenset(quem.roles), request_id=uuid.uuid4(),
    )


def cliente(quem=None):
    c = Client(SERVER_NAME='localhost')
    c.force_login((quem or medico).user)
    sessao = c.session
    sessao['tenant_id'] = str(clinica.id)
    sessao.save()
    return c


print('=== 1. o catalogo e o texto de venda dizem a mesma coisa ===')
ESPERADO = {
    PlanCode.FREE: False, PlanCode.BASIC: False,
    PlanCode.COMPLETE: True, PlanCode.CUSTOM: True,
}
for codigo, esperado in ESPERADO.items():
    tem = has_clinical_ai(codigo)
    # O texto de venda e a outra metade: anunciar IA num plano que o
    # servidor recusa e a divergencia que este gate veio corrigir, e ela
    # volta no dia em que alguem editar so um dos dois lados.
    anuncia = any('IA' in linha for linha in PLANS[codigo]['features'])
    print(f'  {codigo:9} catalogo={tem!s:5} anuncia_na_vitrine={anuncia}')
    if tem != esperado:
        falhas.append(f'{codigo}: catalogo diz {tem}, esperado {esperado}')
    # So uma das direcoes e defeito. **Anunciar e recusar** e a divergencia
    # que este gate veio corrigir -- a pessoa compra e nao recebe. O
    # contrario (o catalogo da, a vitrine cala) nao mente com ninguem: e o
    # caso do Personalizado, cuja vitrine fala de condicoes combinadas em
    # vez de listar recursos. Exigir simetria aqui obrigaria a escrever uma
    # linha de venda que ninguem pediu.
    if anuncia and not tem:
        falhas.append(f'{codigo}: a vitrine anuncia IA e o catalogo recusa')

# O Completo e o unico que **promete** a IA na vitrine, e essa promessa e a
# razao de tudo isto existir: ela estava la sozinha, sem nada no servidor
# cobrando. Se sumir do texto, o gate perde o fundamento.
if not any('IA' in linha for linha in PLANS[PlanCode.COMPLETE]['features']):
    falhas.append('o Completo deixou de anunciar a IA na vitrine')

print('=== 1b. o resumo clinico responde em portugues brasileiro ===')
prompt_resumo = build_prompt('encounter_summary', 'Patient reports headache.')
contrato_ptbr = (
    'português brasileiro' in prompt_resumo.lower()
    and 'valores' in prompt_resumo.lower()
)
print(f'  contrato de idioma no prompt={contrato_ptbr} versao={PROMPT_VERSION}')
if not contrato_ptbr:
    falhas.append('o prompt de resumo nao exige valores textuais em portugues brasileiro')
if PROMPT_VERSION != 'v3':
    falhas.append(f'a mudanca de idioma nao versionou o prompt (esta em {PROMPT_VERSION})')

print(f'  plano inexistente -> {has_clinical_ai("nao-existe")} (tem de ser False)')
if has_clinical_ai('nao-existe'):
    falhas.append('codigo de plano desconhecido liberou a IA')

print('=== 2. a capacidade segue o plano, nao o papel ===')
com_plano(PlanCode.COMPLETE)
com = Capability.CLINICAL_AI in capacidades()
com_plano(PlanCode.BASIC)
sem = Capability.CLINICAL_AI in capacidades()
print(f'  medico verificado: completo={com}  basico={sem}')
if not com:
    falhas.append('o plano Completo nao concedeu CLINICAL_AI')
if sem:
    falhas.append('o plano Basico concedeu CLINICAL_AI')
# O resto do papel medico nao pode ir junto: o gate e da IA, e nao do
# prontuario. Uma clinica sem IA continua sendo uma clinica.
if Capability.READ_CLINICAL not in capacidades():
    falhas.append('o plano sem IA tirou tambem a leitura de prontuario')

print('=== 3. nao da para chamar sem decidir o plano ===')
try:
    capabilities_for(medico.roles, clinically_enabled=True)
    print('  chamada sem `ai_contracted` passou (nao deveria)')
    falhas.append('capabilities_for aceita omitir ai_contracted -- um padrao volta a liberar tudo')
except TypeError as exc:
    print(f'  sem `ai_contracted` -> recusado: {type(exc).__name__}')

print('=== 4. a autorizacao do job recusa, e e ela que guarda o dinheiro ===')
com_plano(PlanCode.BASIC)
try:
    build_ai_authorization(contexto())
    print('  autorizou num plano sem IA (nao deveria)')
    falhas.append('build_ai_authorization autorizou num plano sem IA')
except AIAuthorizationDenied as exc:
    print(f'  plano Basico -> recusado: {exc}')
    if 'plano' not in str(exc).lower():
        falhas.append('a recusa nao diz que o motivo e o plano')
com_plano(PlanCode.COMPLETE)
try:
    build_ai_authorization(contexto())
    print('  plano Completo -> autorizado')
except AIAuthorizationDenied as exc:
    falhas.append(f'o plano Completo foi recusado: {exc}')

print('=== 5. rebaixar entre enfileirar e executar ainda barra ===')
# `run_job` reconstroi a autorizacao do banco imediatamente antes de falar
# com o provedor. Um rebaixamento nessa janela e o mesmo caso de um vinculo
# revogado no meio -- e esta e a ultima chance de nao gastar a chave.
ctx = contexto()
com_plano(PlanCode.FREE)
try:
    build_ai_authorization(ctx)
    print('  o contexto de antes do rebaixamento ainda autorizou (nao deveria)')
    falhas.append('autorizacao montada antes do rebaixamento continuou valendo')
except AIAuthorizationDenied as exc:
    print(f'  rebaixada depois de montar o contexto -> recusado: {exc}')

print('=== 6. o resumo automatico nao cria job, e nao levanta ===')
# Ele nasce de um evento, sem tela. Se levantasse, o despachante
# reentregaria com recuo e marcaria FAILED -- falha falsa a cada
# atendimento finalizado numa clinica sem IA.
encontro = Encounter.objects.filter(
    tenant=clinica, status=EncounterStatus.FINALIZED,
).exclude(finalized_by=None).first()
if encontro is None:
    print('  (sem atendimento finalizado na demonstracao; secao pulada)')
else:
    Tenant.objects.filter(id=clinica.id).update(
        settings={**_settings_original, 'ai_encounter_summary_enabled': True},
    )
    antes = AIJob.objects.filter(tenant=clinica).count()
    evento = SimpleNamespace(payload_minimal={'encounter_id': str(encontro.id)})
    with override_settings(AI_ENABLED=True):
        try:
            handle_encounter_finalized(evento)
            print('  handler no plano Gratuito -> voltou sem levantar')
        except Exception as exc:                            # noqa: BLE001
            print(f'  handler levantou {type(exc).__name__}: {exc}')
            falhas.append(
                'o resumo automatico levantou num plano sem IA -- o evento vira FAILED'
            )
    depois = AIJob.objects.filter(tenant=clinica).count()
    print(f'  jobs antes={antes} depois={depois}')
    if depois != antes:
        falhas.append('o resumo automatico criou job numa clinica sem IA')
    Tenant.objects.filter(id=clinica.id).update(settings=_settings_original)

print('=== 7. as telas: o chat fecha, e o link some junto ===')
com_plano(PlanCode.COMPLETE)
c = cliente()
codigo_com = c.get('/app/ai/chat/').status_code
menu_com = '/app/ai/chat/' in c.get('/app/reporting/').content.decode('utf-8', 'replace')
com_plano(PlanCode.BASIC)
c = cliente()
codigo_sem = c.get('/app/ai/chat/').status_code
menu_sem = '/app/ai/chat/' in c.get('/app/reporting/').content.decode('utf-8', 'replace')
print(f'  /app/ai/chat/  completo={codigo_com}  basico={codigo_sem}')
print(f'  link na barra  completo={menu_com}   basico={menu_sem}')
if codigo_com != 200:
    falhas.append(f'o chat nao abriu no plano Completo ({codigo_com})')
if codigo_sem != 404:
    falhas.append(f'o chat abriu num plano sem IA ({codigo_sem}); esperava 404')
if not menu_com:
    falhas.append('o link do chat sumiu do menu no plano que tem IA')
if menu_sem:
    falhas.append('o link do chat continua no menu num plano sem IA -- 404 na cara de quem clica')

print('=== 8. a configuracao explica, e nao deixa gravar ===')
# Aqui a recusa **nao** e 404 de proposito: quem abre esta tela e quem
# decide o plano, e esconde-la ensinaria que o recurso nao existe. Por isso
# o cliente aqui e o do gestor, e nao o do medico -- o medico sem papel
# administrativo leva 404 por falta de capacidade, que e outra pergunta.
com_plano(PlanCode.BASIC)
g = cliente(gestor)
r = g.get('/app/org/ia/')
corpo = r.content.decode('utf-8', 'replace')
diz_o_motivo = 'não inclui o apoio clínico por IA' in corpo
tem_formulario = 'ai-form' in corpo
print(f'  GET  /app/org/ia/ (gestor, Basico) -> {r.status_code}  '
      f'explica={diz_o_motivo}  formulario={tem_formulario}')
if r.status_code != 200:
    falhas.append(f'a tela de configuracao sumiu num plano sem IA ({r.status_code})')
if not diz_o_motivo:
    falhas.append('a tela nao diz que o plano nao inclui a IA')
if tem_formulario:
    falhas.append('a tela ainda oferece o formulario que o servidor vai recusar')

for rota in ['/app/org/ia/salvar/', '/app/org/ia/modelos/', '/app/org/ia/testar/']:
    codigo = g.post(rota, {'provider': 'openrouter', 'model': 'x'}).status_code
    print(f'  POST {rota:24} (gestor)  -> {codigo}')
    if codigo != 403:
        falhas.append(f'{rota} aceitou gravacao num plano sem IA ({codigo}); esperava 403')

# Quem nao tem a capacidade continua levando 404 -- inclusive no POST.
#
# Foi o defeito que este roteiro pegou na primeira rodada: o bloqueio por
# plano estava **antes** da conferencia de capacidade, e o medico sem papel
# administrativo recebia 403 no POST e 404 no GET da mesma rota. O 403
# contava que a tela existe, que e exatamente o que o 404 do resto de
# `/app/` evita.
sa = cliente(sem_admin)
for verbo, rota in [('GET', '/app/org/ia/'), ('POST', '/app/org/ia/salvar/')]:
    resposta = sa.get(rota) if verbo == 'GET' else sa.post(rota, {'provider': 'openrouter'})
    print(f'  {verbo:4} {rota:24} (sem papel administrativo) -> {resposta.status_code}')
    if resposta.status_code != 404:
        falhas.append(
            f'{verbo} {rota} devolveu {resposta.status_code} a quem nao tem a '
            f'capacidade; esperava 404 -- 403 revela que a tela existe'
        )

com_plano(PlanCode.COMPLETE)
g = cliente(gestor)
corpo = g.get('/app/org/ia/').content.decode('utf-8', 'replace')
print(f'  GET  /app/org/ia/ (gestor, Completo) -> formulario={"ai-form" in corpo}')
if 'ai-form' not in corpo:
    falhas.append('o formulario sumiu tambem no plano que tem IA')

restaurar()
print(f'--- plano da demonstracao restaurado: {Tenant.objects.get(id=clinica.id).plan}')

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: a IA segue o plano, nas telas e no ponto em que a chave seria gasta.')
