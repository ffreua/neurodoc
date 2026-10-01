"""Convenios, planos e valores: quem alcanca, e quem nao.

O que este teste tenta quebrar: secretaria cadastrando convenio, medico
definindo o preco do colega, medico definindo a regra geral da clinica,
plano de uma clinica aparecendo na outra, e duas regras de preco vigentes
ao mesmo tempo — que tornariam o preco indeterminado.
"""
from django.utils import timezone
from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from datetime import date, timedelta

from django.contrib.messages import get_messages

from accounts.models import User
from finance.models import FeeSchedule, PaymentCategory
from patients.models import HealthPlan, Insurer
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
TENANT_B = 'demo-clinica-b'
falhas = []
criados = {'insurers': [], 'plans': [], 'fees': []}


def note(r):
    itens = [str(m) for m in get_messages(r.wsgi_request)]
    return itens[-1] if itens else '(sem aviso)'


def client_for(email, slug=TENANT):
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant__slug=slug)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(membership.tenant_id)
    s.save()
    return c, membership


dono, m_dono = client_for('doctor-a@demo.neurodoc.local')
gestor, m_gestor = client_for('manager-a@demo.neurodoc.local')
secretaria, m_sec = client_for('secretary-a@demo.neurodoc.local')
medico_b, m_medb = client_for('doctor-b@demo.neurodoc.local')

print('=' * 66)
print('1. CONVENIOS E PLANOS')
print('=' * 66)

# --- quem abre a tela ---
for rotulo, c, esperado in [('dono', dono, 200), ('gestor', gestor, 200),
                            ('secretaria', secretaria, 404), ('medico nao-dono', medico_b, 404)]:
    r = c.get('/app/org/convenios/')
    print(f'  {rotulo:18} abre convenios -> {r.status_code}')
    if r.status_code != esperado:
        falhas.append(f'{rotulo} recebeu {r.status_code} em convenios, esperado {esperado}')

# --- o dono cadastra ---
r = dono.post('/app/org/convenios/novo/', {'name': 'Teste Saude', 'ans_registration': '999999',
                                           'active': 'on'}, follow=True)
conv = Insurer.objects.filter(tenant__slug=TENANT, name='Teste Saude').first()
print('  dono cadastra convenio ->', note(r))
if conv is None:
    falhas.append('o dono nao conseguiu cadastrar convenio')
else:
    criados['insurers'].append(conv.id)

# --- duplicata pelo nome ---
if conv:
    antes = Insurer.objects.filter(tenant__slug=TENANT).count()
    r = dono.post('/app/org/convenios/novo/', {'name': 'teste saude', 'active': 'on'})
    depois = Insurer.objects.filter(tenant__slug=TENANT).count()
    print('  convenio duplicado (outra caixa) ->', 'recusado' if depois == antes else 'ACEITO')
    if depois != antes:
        falhas.append('convenio duplicado foi aceito, so mudando maiuscula/minuscula')

# --- plano ---
if conv:
    r = dono.post('/app/org/convenios/planos/novo/', {
        'insurer': str(conv.id), 'name': 'Plano Teste', 'kind': 'ambulatorial', 'active': 'on',
        'administrative_notes': 'exige guia',
    }, follow=True)
    plano = HealthPlan.objects.filter(tenant__slug=TENANT, name='Plano Teste').first()
    print('  dono cadastra plano ->', note(r))
    if plano is None:
        falhas.append('o dono nao conseguiu cadastrar plano')
    else:
        criados['plans'].append(plano.id)

# --- a secretaria tenta gravar direto na rota ---
if conv:
    antes = Insurer.objects.filter(tenant__slug=TENANT).count()
    r = secretaria.post('/app/org/convenios/novo/', {'name': 'Invasao', 'active': 'on'})
    depois = Insurer.objects.filter(tenant__slug=TENANT).count()
    print('  secretaria posta em convenios ->', r.status_code)
    if r.status_code != 404 or depois != antes:
        falhas.append(f'a secretaria cadastrou convenio (HTTP {r.status_code})')

# --- plano da clinica A nao pode ser escolhido na clinica B ---
dono_b, m_dono_b = client_for('doctor-a@demo.neurodoc.local', TENANT_B)
if conv:
    antes = HealthPlan.objects.filter(tenant__slug=TENANT_B).count()
    r = dono_b.post('/app/org/convenios/planos/novo/', {
        'insurer': str(conv.id), 'name': 'Vazamento', 'kind': 'ambulatorial', 'active': 'on',
    })
    depois = HealthPlan.objects.filter(tenant__slug=TENANT_B).count()
    print('  clinica B usa convenio da A ->', 'recusado' if depois == antes else 'ACEITO')
    if depois != antes:
        falhas.append('convenio de outra clinica foi aceito na clinica B')

# --- desativar convenio desativa os planos dele ---
if conv and criados['plans']:
    dono.post(f'/app/org/convenios/{conv.id}/salvar/', {'name': 'Teste Saude',
                                                        'ans_registration': '999999'}, follow=True)
    plano = HealthPlan.objects.get(id=criados['plans'][0])
    print('  desativar convenio -> plano ativo?', plano.active)
    if plano.active:
        falhas.append('o plano continuou ativo depois de o convenio ser desativado')
    # devolve ao estado anterior para o resto do teste
    dono.post(f'/app/org/convenios/{conv.id}/salvar/',
              {'name': 'Teste Saude', 'ans_registration': '999999', 'active': 'on'}, follow=True)
    HealthPlan.objects.filter(id=plano.id).update(active=True)

print()
print('=' * 66)
print('2. VALORES DE CONSULTA E PROCEDIMENTO')
print('=' * 66)

for rotulo, c, esperado in [('dono', dono, 200), ('gestor', gestor, 200),
                            ('medico nao-dono', medico_b, 200), ('secretaria', secretaria, 404)]:
    r = c.get('/app/org/valores/')
    print(f'  {rotulo:18} abre valores -> {r.status_code}')
    if r.status_code != esperado:
        falhas.append(f'{rotulo} recebeu {r.status_code} em valores, esperado {esperado}')

hoje = timezone.localdate()
base = {
    'payment_category': PaymentCategory.PRIVATE, 'plan': '', 'procedure': '',
    'gross_amount': '400.00', 'doctor_share_amount': '280.00',
    'effective_from': hoje.isoformat(), 'effective_to': '',
}

# --- o dono cria a regra geral ---
r = dono.post('/app/org/valores/novo/', dict(base, physician=''), follow=True)
geral = FeeSchedule.objects.filter(tenant__slug=TENANT, physician__isnull=True,
                                   gross_amount='400.00').first()
print('  dono cria regra geral ->', note(r))
if geral is None:
    falhas.append('o dono nao conseguiu criar a regra geral')
else:
    criados['fees'].append(geral.id)

# --- a mesma regra de novo: sobreposicao ---
if geral:
    antes = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
    r = dono.post('/app/org/valores/novo/', dict(base, physician=''))
    depois = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
    print('  regra sobreposta ->', 'recusada' if depois == antes else 'ACEITA')
    if depois != antes:
        falhas.append('duas regras equivalentes vigentes ao mesmo tempo foram aceitas')

# --- o medico nao-dono tenta criar a regra geral ---
antes = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
r = medico_b.post('/app/org/valores/novo/', dict(base, physician='', gross_amount='111.00'))
depois = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
print('  medico cria regra GERAL ->', 'recusado' if depois == antes else 'ACEITO')
if depois != antes:
    falhas.append('um medico criou a regra geral da clinica')

# --- o medico tenta definir o preco do colega ---
antes = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
r = medico_b.post('/app/org/valores/novo/', dict(base, physician=str(m_dono.id),
                                                 gross_amount='1.00'))
depois = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
print('  medico define preco do colega ->', 'recusado' if depois == antes else 'ACEITO')
if depois != antes:
    falhas.append('um medico definiu o valor da consulta de outro medico')

# --- o medico define o proprio preco ---
r = medico_b.post('/app/org/valores/novo/', dict(base, physician=str(m_medb.id),
                                                 gross_amount='350.00'), follow=True)
propria = FeeSchedule.objects.filter(tenant__slug=TENANT, physician=m_medb,
                                     gross_amount='350.00').first()
print('  medico define o proprio preco ->', note(r))
if propria is None:
    falhas.append('o medico nao conseguiu definir o proprio valor')
else:
    criados['fees'].append(propria.id)

# --- repasse maior que o valor cheio ---
antes = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
r = dono.post('/app/org/valores/novo/', dict(
    base, physician=str(m_dono.id), gross_amount='300.00', doctor_share_amount='900.00'))
depois = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
print('  repasse > valor cheio ->', 'recusado' if depois == antes else 'ACEITO')
if depois != antes:
    falhas.append('repasse maior que o valor cheio foi aceito')

# --- plano exigido quando a forma de pagamento e "plano" ---
antes = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
r = dono.post('/app/org/valores/novo/', dict(
    base, physician='', payment_category=PaymentCategory.INSURANCE, plan=''))
depois = FeeSchedule.objects.filter(tenant__slug=TENANT).count()
print('  categoria "plano" sem plano ->', 'recusado' if depois == antes else 'ACEITO')
if depois != antes:
    falhas.append('regra de plano sem plano escolhido foi aceita')

# --- encerrar: o medico nao encerra a regra geral ---
if geral:
    amanha = (hoje + timedelta(days=1)).isoformat()
    r = medico_b.post(f'/app/org/valores/{geral.id}/encerrar/', {'effective_to': amanha},
                      follow=True)
    geral.refresh_from_db()
    print('  medico encerra regra geral ->', note(r))
    if geral.effective_to is not None:
        falhas.append('um medico encerrou a regra geral da clinica')

# --- o dono encerra ---
if geral:
    amanha = (hoje + timedelta(days=1)).isoformat()
    r = dono.post(f'/app/org/valores/{geral.id}/encerrar/', {'effective_to': amanha}, follow=True)
    geral.refresh_from_db()
    print('  dono encerra regra geral ->', note(r))
    if geral.effective_to is None:
        falhas.append('o dono nao conseguiu encerrar a regra geral')

# --- o motor de preco continua respondendo ---
from finance.pricing import NoApplicableFeeSchedule, resolve_price
from tenancy.models import Tenant

try:
    escolhida = resolve_price(Tenant.objects.get(slug=TENANT), m_medb,
                              PaymentCategory.PRIVATE, hoje)
    print('  resolve_price para o medico ->', escolhida.gross_amount,
          '(regra propria)' if escolhida.physician_id == m_medb.id else '(regra geral)')
    if escolhida.physician_id != m_medb.id:
        falhas.append('a regra especifica do medico nao venceu a geral')
except NoApplicableFeeSchedule as exc:
    falhas.append(f'nenhuma regra se aplicou: {exc}')

# ------------------------------------------------- exclusao de plano
#
# Excluir so vale para plano que nunca foi usado. Havendo cobertura de
# paciente ou tabela de valores, apagar apagaria o registro de sob qual
# cobertura alguem foi atendido -- e isso e historia clinica, nao
# cadastro. A saida para o plano em uso e desmarcar "Aceito pela clinica".
print()
print('=== exclusao de plano ===')

from patients.models import PatientCoverage

tenant_obj = Tenant.objects.get(slug=TENANT)

descartavel = HealthPlan.objects.create(
    tenant=tenant_obj, insurer=Insurer.objects.filter(tenant=tenant_obj).first(),
    name='Plano Digitado Errado (check)',
)
r = dono.post(f'/app/org/convenios/planos/{descartavel.id}/excluir/', follow=True)
sumiu = not HealthPlan.objects.filter(id=descartavel.id).exists()
print(f'  plano sem uso        -> {r.status_code}  excluido={sumiu}')
if not sumiu:
    falhas.append('plano que nunca foi usado nao pode ser excluido')

em_uso = None
for candidato in HealthPlan.objects.filter(tenant=tenant_obj):
    if PatientCoverage.objects.filter(plan=candidato).exists():
        em_uso = candidato
        break

if em_uso is None:
    print('  (nenhum plano em uso na demonstracao -- nao da para provar aqui)')
else:
    r = dono.post(f'/app/org/convenios/planos/{em_uso.id}/excluir/', follow=True)
    corpo = r.content.decode()
    resistiu = HealthPlan.objects.filter(id=em_uso.id).exists()
    util = 'paciente(s)' in corpo and 'Aceito pela' in corpo
    print(f'  plano em uso         -> {r.status_code}  resistiu={resistiu}  recusa util={util}')
    if not resistiu:
        falhas.append('um plano em uso foi excluido, e com ele o registro de cobertura')
    if not util:
        falhas.append('a recusa nao diz quem prende o plano nem oferece a saida')

# O botao so aparece para o que pode ser apagado: oferecer o que sera
# negado e pior do que nao oferecer.
corpo = dono.get('/app/org/convenios/').content.decode()
na_tela = corpo.count('/excluir/')
sem_uso = sum(
    1 for pl in HealthPlan.objects.filter(tenant=tenant_obj)
    if not PatientCoverage.objects.filter(plan=pl).exists()
    and not FeeSchedule.objects.filter(plan=pl).exists()
)
print(f'  botoes na tela={na_tela}  planos sem uso={sem_uso}  confere={na_tela == sem_uso}')
if na_tela != sem_uso:
    falhas.append(f'a tela oferece {na_tela} exclusoes para {sem_uso} planos elegiveis')

# Secretaria nao administra convenio: a capacidade e MANAGE_HEALTH_PLANS.
outro = HealthPlan.objects.create(
    tenant=tenant_obj, insurer=Insurer.objects.filter(tenant=tenant_obj).first(),
    name='Plano Alvo Da Secretaria (check)',
)
r = secretaria.post(f'/app/org/convenios/planos/{outro.id}/excluir/')
sobreviveu = HealthPlan.objects.filter(id=outro.id).exists()
print(f'  secretaria excluindo -> {r.status_code}  plano sobreviveu={sobreviveu}')
if not sobreviveu:
    falhas.append('a secretaria conseguiu excluir um plano')
criados['plans'].append(outro.id)

# ---------------------------------------------------------------- limpeza
FeeSchedule.objects.filter(id__in=criados['fees']).delete()
HealthPlan.objects.filter(id__in=criados['plans']).delete()
Insurer.objects.filter(id__in=criados['insurers']).delete()
print()
print('limpeza:', len(criados['fees']), 'valores,', len(criados['plans']), 'planos,',
      len(criados['insurers']), 'convenios removidos')

print()
print('=== exclusao de convenio ===')
# A cadeia se le de baixo para cima: o plano so sai quando ninguem o usou, e
# o convenio so sai quando nao tem mais plano. Apagar convenio com plano
# levaria junto o registro de sob qual cobertura o paciente foi atendido.

vazio = Insurer.objects.create(tenant=tenant_obj, name='Convenio Digitado Errado (check)')
r = dono.post(f'/app/org/convenios/{vazio.id}/excluir/', follow=True)
sumiu = not Insurer.objects.filter(id=vazio.id).exists()
print(f'  convenio sem plano   -> {r.status_code}  excluido={sumiu}')
if not sumiu:
    falhas.append('convenio sem plano nenhum nao pode ser excluido')

com_plano = (
    Insurer.objects.filter(tenant=tenant_obj, plans__isnull=False).distinct().first()
)
if com_plano is None:
    print('  (nenhum convenio com plano na demonstracao -- nao da para provar aqui)')
else:
    rotulo = str(com_plano)
    r = dono.post(f'/app/org/convenios/{com_plano.id}/excluir/', follow=True)
    resistiu = Insurer.objects.filter(id=com_plano.id).exists()
    corpo = r.content.decode('utf-8', 'replace')
    explica = 'nao pode ser excluido' in corpo or 'não pode ser excluído' in corpo
    print(f'  convenio com plano   -> {r.status_code}  resistiu={resistiu}  '
          f'a tela diz por que={explica}')
    if not resistiu:
        falhas.append(
            f'{rotulo} tinha plano e foi apagado — isso levaria junto o registro '
            f'de sob qual cobertura o paciente foi atendido'
        )
    if not explica:
        falhas.append('a recusa de excluir convenio nao explica o que o prende')

# Quem nao administra a clinica nao apaga convenio, mesmo com o id na mao.
descartavel_sec = Insurer.objects.create(tenant=tenant_obj, name='Convenio da secretaria (check)')
codigo = secretaria.post(f'/app/org/convenios/{descartavel_sec.id}/excluir/').status_code
sobreviveu = Insurer.objects.filter(id=descartavel_sec.id).exists()
print(f'  secretaria tenta     -> {codigo}  sobreviveu={sobreviveu}')
if codigo != 404 or not sobreviveu:
    falhas.append(f'secretaria conseguiu chegar na exclusao de convenio ({codigo})')
descartavel_sec.delete()

print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: convenios, planos e valores respeitam quem pode o que.')
