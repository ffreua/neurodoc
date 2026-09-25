"""As duas decisoes de negocio da auditoria pre-deploy, agora em codigo.

**D-01 -- o endereco da API do provedor de IA.** O campo "endereco da API"
existe para servidor proprio (Ollama, vLLM), e chegava do POST sem validacao
nenhuma ate o `httpx`. Isso importa porque o processo `app` **nao alcanca a
internet** em producao: o que ele alcanca e a rede interna -- `db`,
`rabbitmq`, `redis`, `traefik` -- e o endereco de metadados do provedor de
nuvem. Um gestor de clinica (cliente, nao operador) apontava o campo para
`http://169.254.169.254/` e o servidor ia la por ele. E `_friendly_http_error`
devolvia mensagem distinta por faixa de status, o que transformava a falha
num varredor de portas com resposta legivel.

A escolha foi **lista de permissao** (`AI_BASE_URL_ALLOWLIST`), vazia por
padrao, e nao "bloquear faixa privada" -- que quebraria o Ollama, que e
justamente um endereco privado, e ainda seria contornavel por hostname
publico resolvendo para IP interno.

**D-02 -- a coleta de lixo do disco.** `garbage_collect` existia pronta,
cuidadosa, e **nao era chamada por ninguem** em producao. O arquivo de um
anexo que o usuario mandou remover ficava legivel em disco para sempre.
Agora ela e semanal e **comeca em ensaio**: conta e registra, nao apaga.
Virar o ensaio e mudanca de `.env`, nao de codigo.

Tenta quebrar. As perguntas sao:

- os provedores do catalogo continuam passando?
- metadados de nuvem, rede interna, porta de banco e `file://` sao recusados
  **antes** de qualquer requisicao sair?
- um host liberado pela instalacao passa -- e so ele?
- a recusa acontece tambem ao **salvar**, e nao so ao consultar o provedor?
  (salvar nao chama ninguem, mas quem usa o valor depois e o worker, que
  alcanca a internet)
- a mensagem de erro do provedor ainda distingue 401 de 404 de 429?
- a coleta de lixo esta agendada, e comeca em ensaio?
- o interruptor do ensaio chega ao worker, ou fica so no settings?
"""
import atexit
from unittest.mock import patch

from django.conf import settings

falhas = []

from ai.providers.catalog import (
    PROVIDERS, ProviderProbeFailed, assert_endereco_permitido, enderecos_do_catalogo,
)

from base.models import InstallationSettings

#: A lista mora no BANCO, e nao no `.env` -- ver `/instalacao/operacao/`.
#: `override_settings` nao a alcanca mais, e um roteiro que continuasse
#: usando aquilo passaria por acidente: estaria testando uma lista vazia
#: achando que testava uma cheia.
_config = InstallationSettings.carregar()
_lista_original = _config.ai_base_url_allowlist


@atexit.register
def _restaurar_lista():
    InstallationSettings.objects.filter(pk=_config.pk).update(
        ai_base_url_allowlist=_lista_original,
    )


def com_lista(*hosts):
    """Deixa a instalacao com exatamente estes hosts liberados."""
    InstallationSettings.objects.filter(pk=_config.pk).update(
        ai_base_url_allowlist=chr(10).join(hosts),
    )


print('=== 1. os provedores do catalogo passam ===')
for endereco in sorted(enderecos_do_catalogo()):
    try:
        assert_endereco_permitido(endereco)
        print(f'  {endereco[:58]:58} ok')
    except ProviderProbeFailed as exc:
        print(f'  {endereco[:58]:58} RECUSADO')
        falhas.append(f'o catalogo traz {endereco} e a validacao o recusa: {exc}')

print('=== 2. o que tem de ser recusado ANTES de sair requisicao ===')
RECUSAR = [
    'http://169.254.169.254/latest/meta-data',   # metadados da nuvem
    'http://db:5432',                             # banco, pela rede do Swarm
    'http://rabbitmq:15672/api/overview',
    'http://redis:6379',
    'http://127.0.0.1:8000/',
    'http://localhost/',
    'http://10.0.0.7:11434',
    'file:///etc/passwd',
    'gopher://interno/',
    'https://provedor-que-ninguem-liberou.invalid/v1',
]
com_lista()
for endereco in RECUSAR:
    try:
        assert_endereco_permitido(endereco)
        print(f'  {endereco[:46]:46} ACEITOU (nao deveria)')
        falhas.append(f'{endereco} foi aceito sem estar na lista de permissao')
    except ProviderProbeFailed:
        print(f'  {endereco[:46]:46} recusado')

print('=== 3. a lista da instalacao libera o servidor proprio ===')
com_lista('ollama.interno', '10.0.0.7:11434')
for endereco, deve_passar in [
    ('http://ollama.interno:11434/v1', True),
    ('http://10.0.0.7:11434/v1', True),
    ('http://outro.interno:11434/v1', False),
    ('http://169.254.169.254/', False),
]:
    try:
        assert_endereco_permitido(endereco)
        passou = True
    except ProviderProbeFailed:
        passou = False
    print(f'  {endereco[:40]:40} -> {"aceito" if passou else "recusado"}')
    if passou != deve_passar:
        falhas.append(
            f'{endereco}: esperava {"aceito" if deve_passar else "recusado"}'
        )

print('=== 4. nenhuma requisicao sai de endereco nao liberado ===')
# A pergunta que importa nao e "deu erro?" e sim "chegou a sair pacote?".
# Um roteiro que so conferisse a mensagem passaria mesmo se a requisicao
# tivesse saido e falhado depois.
from ai.providers import catalog

com_lista()
with patch.object(catalog.httpx, 'Client') as cliente_falso:
    for funcao, args in [
        (catalog.list_models, ('custom', 'chave-de-mentira', 'http://169.254.169.254/')),
        (catalog.probe_model, ('custom', 'chave-de-mentira', 'modelo', 'http://db:5432')),
    ]:
        try:
            funcao(*args)
        except ProviderProbeFailed:
            pass
    saiu = cliente_falso.called
    print(f'  httpx.Client foi instanciado: {saiu} (tem de ser False)')
    if saiu:
        falhas.append('saiu requisicao para endereco nao liberado')

print('=== 5. a recusa vale tambem ao SALVAR ===')
# Salvar nao chama o provedor -- mas grava o endereco, e quem o usa depois e
# o worker, que alcanca a internet.
from ai.forms import AIProviderSettingsForm

com_lista()
formulario = AIProviderSettingsForm(data={
    'provider': 'custom', 'base_url': 'http://169.254.169.254/', 'model': '',
})
formulario.is_valid()
recusou = 'base_url' in formulario.errors
print(f'  salvar endereco de metadados -> {"recusado" if recusou else "ACEITOU"}')
if not recusou:
    falhas.append('o formulario gravaria um endereco que a lista nao libera')

print('=== 6. a mensagem de erro nao distingue status ===')
# Uma mensagem por faixa de status da um oraculo de varredura: aponta-se o
# campo para uma porta interna e le-se, pela mensagem, se o host existe, se
# a porta responde e se ela pede credencial.
import httpx

mensagens = set()
for status in (401, 403, 404, 429, 500, 503, 418):
    resposta = httpx.Response(status, request=httpx.Request('GET', 'https://x.invalid/'))
    erro = httpx.HTTPStatusError('x', request=resposta.request, response=resposta)
    mensagens.add(catalog._friendly_http_error(erro))
print(f'  mensagens distintas para 7 status diferentes: {len(mensagens)}')
if len(mensagens) != 1:
    falhas.append(
        f'a mensagem de erro varia com o status ({len(mensagens)} versoes) — '
        f'isso e um oraculo de varredura de porta'
    )

print('=== 7. a coleta de lixo esta agendada, e em ensaio ===')
agenda = settings.CELERY_BEAT_SCHEDULE
entrada = next(
    (v for v in agenda.values() if v['task'] == 'documents.tasks.garbage_collect'),
    None,
)
print(f'  agendada: {entrada is not None}')
if entrada is None:
    falhas.append('a coleta de lixo do disco continua sem agendamento')

# O padrao vem do `.env` e semeia a linha; quem decide depois e o banco.
ensaio = getattr(settings, 'DOCUMENTS_GC_DRY_RUN', None)
print(f'  DOCUMENTS_GC_DRY_RUN (semente do .env) = {ensaio!r}')
if ensaio is not True:
    falhas.append(
        'o ensaio da coleta nao esta ligado por padrao — ligar o apagamento '
        'permanente e decisao do controlador, nao padrao de codigo'
    )

print('=== 8. o interruptor chega ao worker ===')
# Um interruptor que fica so no settings e o operador vira no `.env` sem
# efeito nenhum: o processo cai no default e ninguem percebe.
from ops.make_runtime import COMMON_KEYS, OPTIONAL_KEYS

passa = set(COMMON_KEYS) | set(OPTIONAL_KEYS)
for chave in ('DOCUMENTS_GC_DRY_RUN', 'AI_BASE_URL_ALLOWLIST'):
    print(f'  {chave:26} chega ao conteiner: {chave in passa}')
    if chave not in passa:
        falhas.append(f'{chave} nao e repassada aos servicos: virar o `.env` nao teria efeito')

print('=== 9. a tarefa devolve o que se quer ler no ensaio ===')
from documents.tasks import garbage_collect_task

resultado = garbage_collect_task()
print(f'  {resultado}')
if resultado.get('skipped'):
    print('  (backup em andamento; a tarefa desistiu, que e o comportamento certo)')
else:
    for chave in ('dry_run', 'removed', 'held_by_retention'):
        if chave not in resultado:
            falhas.append(f'a tarefa nao informa {chave} — o ensaio serve para ler esses numeros')
    if resultado.get('dry_run') is not True:
        falhas.append('a tarefa rodou FORA do ensaio com o padrao do settings')

print('=== 10. a tela de operacao existe e exige MFA ===')
# As duas chaves acima se viram por aqui, sem republicar o stack. O motivo
# nao e conveniencia: e que **desligar demorava um ciclo de deploy**, e uma
# trava que so se solta republicando nao serve de freio de emergencia.
from django.conf import settings as dj_settings
from django.test import Client
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User
from audit.models import AuditEvent
from base.models import InstallationSettings

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

superadmin = User.objects.filter(is_superuser=True, is_active=True).first()
if superadmin is None:
    print('  (sem superusuario nesta instalacao; secoes 10-14 puladas)')
else:
    config = InstallationSettings.carregar()
    _antes = (config.ai_base_url_allowlist, config.documents_gc_dry_run, config.documents_gc_note)

    @atexit.register
    def _restaurar_operacao():
        InstallationSettings.objects.filter(pk=config.pk).update(
            ai_base_url_allowlist=_antes[0],
            documents_gc_dry_run=_antes[1],
            documents_gc_note=_antes[2],
        )
        TOTPDevice.objects.filter(user=superadmin, name='roteiro-decisoes').delete()

    cliente = Client(SERVER_NAME='localhost')
    cliente.force_login(superadmin)
    sem_mfa = cliente.get('/instalacao/operacao/').status_code
    print(f'  GET sem MFA -> {sem_mfa} (404 esperado)')
    if sem_mfa != 404:
        falhas.append(
            f'a tela de operacao abriu sem MFA ({sem_mfa}) — ela liga e desliga '
            f'apagamento de arquivo clinico'
        )

    aparelho, _ = TOTPDevice.objects.get_or_create(
        user=superadmin, name='roteiro-decisoes', defaults={'confirmed': True},
    )
    if not aparelho.confirmed:
        aparelho.confirmed = True
        aparelho.save(update_fields=['confirmed'])
    sessao = cliente.session
    sessao[DEVICE_ID_SESSION_KEY] = aparelho.persistent_id
    sessao.save()
    com_mfa = cliente.get('/instalacao/operacao/').status_code
    print(f'  GET com MFA -> {com_mfa}')
    if com_mfa != 200:
        falhas.append(f'a tela de operacao nao abriu para superusuario com MFA ({com_mfa})')

    print('=== 11. o banco manda, e vale sem republicar ===')
    # Se o `.env` continuasse mandando, virar a chave na tela nao faria nada
    # -- e o operador acharia que fez.
    cliente.post('/instalacao/operacao/ia/', {'allowlist': 'ollama.doroteiro\n10.9.9.9:11434'})
    try:
        assert_endereco_permitido('http://ollama.doroteiro:11434/v1')
        valeu = True
    except ProviderProbeFailed:
        valeu = False
    print(f'  endereco gravado pela tela vale na hora: {valeu}')
    if not valeu:
        falhas.append(
            'o que se grava na tela nao vale: a validacao continua lendo o `.env`, '
            'e virar a lista no console nao teria efeito'
        )

    print('=== 12. ligar o apagamento exige confirmacao E motivo ===')
    for rotulo, dados in [
        ('so o motivo', {'acao': 'apagar', 'motivo': 'porque sim'}),
        ('so a confirmacao', {'acao': 'apagar', 'confirmacao': 'APAGAR'}),
        ('confirmacao errada', {'acao': 'apagar', 'confirmacao': 'apagar', 'motivo': 'x'}),
    ]:
        cliente.post('/instalacao/operacao/coleta/', dados)
        config.refresh_from_db()
        print(f'  {rotulo:20} -> ensaio continua ligado: {config.documents_gc_dry_run}')
        if not config.documents_gc_dry_run:
            falhas.append(f'o apagamento foi ligado com "{rotulo}"')
            config.documents_gc_dry_run = True
            config.save(update_fields=['documents_gc_dry_run'])

    cliente.post('/instalacao/operacao/coleta/', {
        'acao': 'apagar', 'confirmacao': 'APAGAR', 'motivo': 'roteiro de verificacao',
    })
    config.refresh_from_db()
    print(f'  confirmacao + motivo -> apagando: {not config.documents_gc_dry_run}')
    if config.documents_gc_dry_run:
        falhas.append('nao foi possivel autorizar o apagamento nem com confirmacao e motivo')

    print('=== 13. voltar ao ensaio e UM clique ===')
    # Assimetria de proposito: parar de apagar e a direcao segura, e uma
    # pergunta a mais aqui custaria justamente o tempo que importa.
    cliente.post('/instalacao/operacao/coleta/', {'acao': 'ensaio'})
    config.refresh_from_db()
    print(f'  sem confirmacao, sem motivo -> de volta ao ensaio: {config.documents_gc_dry_run}')
    if not config.documents_gc_dry_run:
        falhas.append('o freio de emergencia nao funcionou com um clique')

    print('=== 14. as tres acoes entram na trilha ===')
    registradas = set(
        AuditEvent.objects.filter(action__startswith='ops.')
        .values_list('action', flat=True)[:20]
    )
    for acao in ('ops.ai_allowlist_changed', 'ops.documents_gc_armed', 'ops.documents_gc_disarmed'):
        print(f'  {acao:32} na trilha: {acao in registradas}')
        if acao not in registradas:
            falhas.append(f'{acao} nao foi registrada na trilha')

    _restaurar_operacao()

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o endereco da IA e lista de permissao, e a coleta de lixo comeca contando.')
