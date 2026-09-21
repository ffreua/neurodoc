"""O console da instalacao, do lado de dentro.

O outro teste provou que ele recusa. Este prova que ele serve — e que o
que ele mostra nao inclui conteudo clinico, que e a decisao que governa o
recurso.
"""
import uuid

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from clinical.models import Encounter
from patients.models import Patient

falhas = []
criados = []

def superadmin_descartavel():
    """Um superadministrador **do roteiro**, nunca a conta de uma pessoa.

    `force_login` grava `last_login`, e `last_login` entra no hash de
    `default_token_generator`: logar numa conta invalida o link de
    definicao de senha pendente dela. Pegar "o primeiro superusuario"
    funcionava enquanto havia contas de teste no banco; num banco limpo,
    a unica conta com `is_superuser` e a de quem opera o sistema -- e o
    roteiro passava a derrubar o link dessa pessoa.
    """
    from accounts.models import User as _User
    from django.utils import timezone as _tz

    conta, criada = _User.objects.get_or_create(
        email='check-superadmin@example.invalid',
        defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
    )
    if criada:
        conta.set_password('CheckS3nha!2026')
    conta.is_staff = True
    conta.is_superuser = True
    conta.is_active = True
    conta.email_verified_at = conta.email_verified_at or _tz.now()
    conta.save()
    return conta


su = superadmin_descartavel()
if su is None:
    raise SystemExit('sem superusuario para testar')

device = TOTPDevice.objects.filter(user=su, confirmed=True).first()
if device is None:
    device = TOTPDevice.objects.create(user=su, name='teste', confirmed=True)
    criados.append(device.id)

# Sessao com o segundo fator ja verificado. `force_login` sozinho nao
# marca `is_verified()`; e essa diferenca que o console exige.
client = Client()
client.force_login(su)
request = type('R', (), {'session': client.session, 'user': su})()
otp_login(request, device)
request.session.save()
client.cookies['sessionid'] = request.session.session_key

print('superusuario:', su.email, '| MFA verificada na sessao')
print()

# A conta e procurada pela busca, e nao esperada na primeira pagina.
#
# A lista de usuarios corta em `PAGE_SIZE` e ordena por e-mail: numa
# instalacao com mais de cem contas -- que e o caso deste banco depois de
# a bateria rodar algumas vezes --, a conta do roteiro cai fora da
# primeira pagina e o roteiro acusava a tela de nao mostrar quem ela
# mostra. Buscar e o que uma pessoa faria, e e o que a tela oferece.
rotas = {
    '/instalacao/': ['Organiza', 'Servi', 'Banco de dados'],
    '/instalacao/organizacoes/': ['Todas as cl'],
    '/instalacao/usuarios/': ['Contas da instala'],
    f'/instalacao/usuarios/?q={su.email}': ['Contas da instala', su.email],
    '/instalacao/auditoria/': ['Trilha'],
}
for rota, esperados in rotas.items():
    r = client.get(rota)
    corpo = r.content.decode(errors='replace')
    faltando = [t for t in esperados if t not in corpo]
    print(f'  {rota:32} -> {r.status_code} {"" if not faltando else "FALTA " + str(faltando)}')
    if r.status_code != 200:
        falhas.append(f'{rota} devolveu {r.status_code} para superusuario com MFA')
    elif faltando:
        falhas.append(f'{rota} nao mostrou {faltando}')

# --- o console avisa o que esta frouxo na instalacao ---
#
# `SECURE_HSTS_SECONDS` comeca em 0 de proposito -- o navegador guarda a
# instrucao, e liga-la antes de o HTTPS funcionar nao tem desfazer. Mas
# nada lembrava de troca-lo depois, e uma instalacao seguia sem HSTS
# porque o dia de ligar nunca entrou na lista de ninguem. Agora o console
# diz, e este trecho confere que ele diz **e** que fica quieto quando nao
# ha o que dizer.
print()
print('=== 6b. avisos de seguranca na visao geral ===')
from ops.superadmin import _avisos_de_seguranca


def _com_config(**mudancas):
    antes = {k: getattr(dj_settings, k) for k in mudancas}
    for k, v in mudancas.items():
        setattr(dj_settings, k, v)
    try:
        return [a['titulo'] for a in _avisos_de_seguranca()]
    finally:
        for k, v in antes.items():
            setattr(dj_settings, k, v)


producao = dict(PUBLIC_BASE_URL='https://neurodoc.app.br', DEBUG=False,
                SECRETS_MASTER_KEY='x', SECURE_HSTS_INCLUDE_SUBDOMAINS=True)

casos = [
    ('HTTPS com HSTS desligado avisa',
     _com_config(**producao, SECURE_HSTS_SECONDS=0), True),
    ('HTTPS com HSTS ligado nao avisa',
     _com_config(**producao, SECURE_HSTS_SECONDS=31536000), False),
    # O silencio em desenvolvimento importa tanto quanto o aviso: um
    # alerta que aparece sempre deixa de ser lido, e ai o dia em que ele
    # importa passa despercebido.
    ('HTTP local nao avisa (0 e o certo ali)',
     _com_config(PUBLIC_BASE_URL='http://localhost:8000', DEBUG=False,
                 SECRETS_MASTER_KEY='x', SECURE_HSTS_SECONDS=0), False),
]
for descricao, titulos, espera_aviso in casos:
    tem = any('HSTS desligado' in t for t in titulos)
    ok = tem == espera_aviso
    print(f'  {"ok  " if ok else "FALHA"} {descricao} -> {titulos or "nenhum"}')
    if not ok:
        falhas.append(descricao)

# DEBUG e chave-mestra ausente entram pela mesma porta.
titulos = _com_config(PUBLIC_BASE_URL='https://neurodoc.app.br', DEBUG=True,
                      SECRETS_MASTER_KEY='', SECURE_HSTS_SECONDS=31536000,
                      SECURE_HSTS_INCLUDE_SUBDOMAINS=True)
print(f'  {"ok  " if len(titulos) == 2 else "FALHA"} DEBUG e chave-mestra tambem sao avisados -> {titulos}')
if len(titulos) != 2:
    falhas.append('o console nao avisou DEBUG ligado e chave-mestra ausente')

# E a tela renderiza com os avisos, em vez de estourar no template.
r = client.get('/instalacao/')
corpo_visao = r.content.decode(errors='replace')
tem_linha_hsts = 'HSTS' in corpo_visao
print(f'  {"ok  " if r.status_code == 200 and tem_linha_hsts else "FALHA"} '
      f'a visao geral abre e mostra o estado do HSTS (HTTP {r.status_code})')
if r.status_code != 200 or not tem_linha_hsts:
    falhas.append('a visao geral nao mostrou o estado do HSTS')

# --- a trilha atravessa organizacoes ---
r = client.get('/instalacao/auditoria/')
corpo = r.content.decode(errors='replace')
tenants_na_trilha = set(
    AuditEvent.objects.exclude(tenant__isnull=True).values_list('tenant__slug', flat=True)[:200]
)
print()
print('  organizacoes com eventos:', len(tenants_na_trilha))
if len(tenants_na_trilha) < 2:
    print('  (a demonstracao tem eventos em menos de duas clinicas — nao da para provar aqui)')

# --- filtro por desfecho ---
r = client.get('/instalacao/auditoria/?outcome=denied')
print('  filtro outcome=denied ->', r.status_code)
if r.status_code != 200:
    falhas.append('o filtro por desfecho quebrou')

# --- busca de usuario ---
r = client.get('/instalacao/usuarios/?q=secretary')
corpo = r.content.decode(errors='replace')
print('  busca "secretary" acha ->', 'secretary-a@demo.neurodoc.local' in corpo)
if 'secretary-a@demo.neurodoc.local' not in corpo:
    falhas.append('a busca de usuarios nao encontrou uma conta existente')

# --- e o que ele NAO mostra: conteudo clinico ---
#
# A afirmacao do recurso e que auditar e saber quem fez o que, e nao ler o
# que foi escrito. Se um texto de prontuario aparecer numa destas telas, a
# afirmacao e falsa.
# A agulha precisa ser longa o bastante para significar alguma coisa.
#
# Era `Encounter.objects.exclude(chief_complaint='').first()`, e isso pegava
# o que outros roteiros deixam para tras: encontros de montagem com queixa
# de uma letra -- 'x', 'y', 'iso'. Procurar 'y' no HTML de qualquer pagina
# acha sempre, e o roteiro passou a acusar vazamento de prontuario no
# console em quatro rotas onde nao havia vazamento nenhum.
#
# Acusacao falsa de vazamento clinico e pior do que nenhuma verificacao:
# manda procurar defeito inexistente numa area sensivel, e ensina a ignorar
# o alarme -- justamente o alarme que deve ser levado a serio quando tocar.
MINIMO_AGULHA = 12
enc = next((e for e in Encounter.objects.exclude(chief_complaint='')
            if len(e.chief_complaint) >= MINIMO_AGULHA), None)
if enc is None:
    print(f'  AVISO: nenhum atendimento com queixa de {MINIMO_AGULHA}+ caracteres; '
          'a busca por vazamento clinico nao foi exercitada. Rode seed_demo.')
paciente = next((p for p in Patient.objects.all()
                 if len(p.full_name or '') >= MINIMO_AGULHA), None)
vazamentos = []
for rota in rotas:
    corpo = client.get(rota).content.decode(errors='replace')
    if enc is not None and enc.chief_complaint and enc.chief_complaint[:30] in corpo:
        vazamentos.append(f'{rota}: queixa principal de atendimento')
    if paciente is not None and paciente.cpf and paciente.cpf in corpo:
        vazamentos.append(f'{rota}: CPF de paciente')
    if paciente is not None and paciente.full_name and paciente.full_name in corpo:
        vazamentos.append(f'{rota}: nome de paciente')
print()
print('  conteudo clinico nas telas ->', vazamentos or 'nenhum')
if vazamentos:
    falhas.extend(f'vazamento no console: {v}' for v in vazamentos)

# --- nem segredo ---
segredos = []
for rota in rotas:
    corpo = client.get(rota).content.decode(errors='replace')
    if dj_settings.SECRET_KEY[:16] in corpo:
        segredos.append(f'{rota}: SECRET_KEY')
    if dj_settings.SECRETS_MASTER_KEY and str(dj_settings.SECRETS_MASTER_KEY)[:12] in corpo:
        segredos.append(f'{rota}: SECRETS_MASTER_KEY')
print('  segredos nas telas ->', segredos or 'nenhum')
if segredos:
    falhas.extend(f'segredo exposto: {s}' for s in segredos)

TOTPDevice.objects.filter(id__in=criados).delete()

# --- a conta descartavel sai junto ---
#
# Ela nasce com `is_superuser`, `is_staff` e senha conhecida (esta escrita
# tres telas acima, neste arquivo). Deixa-la no banco depois da rodada e
# deixar uma porta de acesso total dormindo na base de desenvolvimento de
# quem rodou o roteiro -- e a senha nao e segredo nenhum, esta versionada.
#
# `AuditEvent.actor` e PROTECT: a conta so sairia depois dos eventos que
# ela gerou, e desde `audit/0003_auditevent_imutavel` a trilha nao pode
# mais ser apagada -- nem aqui. Ate entao este bloco tirava os eventos da
# frente para poder apagar a conta; era o proprio roteiro contornando a
# propriedade que o sistema promete, e a primeira coisa que a protecao
# quebrou foi este atalho, que e o sinal de que ela funciona.
#
# Entao a conta e **aposentada**, nao apagada: perde os poderes, perde a
# senha e perde o e-mail (que volta a ficar livre para a proxima rodada).
# Como porta de acesso ela deixa de existir, que era a preocupacao; e a
# linha que a trilha aponta continua de pe, que e como auditoria funciona.
from accounts.models import User as _User
from audit.models import AuditEvent as _AuditEvent

_eventos = _AuditEvent.objects.filter(actor=su).count()
_conta = su.email
su.set_unusable_password()
su.is_active = False
su.is_staff = False
su.is_superuser = False
su.email = f'aposentado-por-roteiro-{uuid.uuid4().hex[:12]}@example.invalid'
su.save(update_fields=['password', 'is_active', 'is_staff', 'is_superuser', 'email'])
_ainda_pode_entrar = _User.objects.filter(
    id=su.id, is_active=True,
).exists() or su.has_usable_password()
print(f'  limpeza -> conta {_conta} aposentada '
      f'({_eventos} evento(s) de auditoria preservados)')
print(f'  a conta ainda serve de porta: {_ainda_pode_entrar}')
if _ainda_pode_entrar:
    falhas.append('a conta descartavel continuou utilizavel depois da limpeza')
print()
print('---')
if falhas:
    for f in falhas:
        print('FALHA:', f)
    raise SystemExit(1)
print('OK: o console serve a quem opera o servidor, e nao abre prontuario.')
