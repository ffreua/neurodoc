"""O que o alerta de erro leva por e-mail para quem opera o servidor.

Nasceu de um defeito real, encontrado na auditoria pre-deploy de
2026-09-24. Com `ALERT_ADMIN_EMAILS` preenchido, todo 500 nao tratado faz
o `AdminEmailHandler` mandar um relatorio por SMTP. Medido antes da
correcao, esse relatorio tinha 16.876 caracteres e levava:

- o despejo dos **206 settings**, com a senha do Redis e a do RabbitMQ em
  texto claro -- elas moram dentro da URL de conexao
  (`amqp://neurodoc:SENHA@rabbitmq:5672/...`), e a filtragem do Django
  decide pelo **nome** do setting (`API|TOKEN|KEY|SECRET|PASS|SIGNATURE`),
  que `CELERY_BROKER_URL` e `REDIS_BASE` nao casam;
- a URL inteira e a secao `GET`, com o termo de busca -- e a busca de
  paciente e por query string (`/app/patients/?q=Carlos`);
- o mesmo termo de novo em `QUERY_STRING`, na secao META.

O `RedactSensitiveDataFilter` nao alcancava nada disso: ele age sobre a
mensagem do registro de log, e o corpo do e-mail e montado a parte, pelo
`ExceptionReporter`.

Tenta quebrar. As perguntas sao:

- a senha do Redis e a do RabbitMQ saem no corpo do alerta?
- o termo de busca sai, na URL, na secao GET ou em QUERY_STRING?
- a classe que o Django usa e mesmo a da casa, ou alguem trocou o setting?
- o corpo do POST e as variaveis locais continuam suprimidos?
- um setting NOVO com credencial embutida ja nasce escondido? (a decisao e
  pelo valor, nao por uma lista de nomes -- e esta secao e o que prova)
"""
import sys

from django.conf import settings
from django.test import RequestFactory, override_settings
from django.views.debug import get_exception_reporter_class

falhas = []

pedido = RequestFactory().get('/app/patients/?q=Carlos%20Adulto')
Reporter = get_exception_reporter_class(pedido)
print('=== 1. a classe que o Django usa ===')
print(f'  {Reporter.__module__}.{Reporter.__name__}')
if Reporter.__module__ != 'base.logging':
    falhas.append(
        f'DEFAULT_EXCEPTION_REPORTER aponta para {Reporter.__module__} — o '
        f'relatorio voltou a ser o do Django, sem as supressoes da casa'
    )


def corpo(req=None):
    req = req or pedido
    try:
        raise ValueError('erro sintetico do roteiro de verificacao')
    except ValueError:
        classe = get_exception_reporter_class(req)
        return classe(req, *sys.exc_info(), is_email=True).get_traceback_text()


texto = corpo()
print(f'  corpo do alerta: {len(texto)} caracteres')

print('=== 2. segredo de conexao no despejo de settings ===')
# Extraidos do proprio settings para o roteiro nao carregar segredo escrito.
alvos = {}
try:
    alvos['senha do Redis'] = settings.CACHES['default']['LOCATION'].split(':')[2].split('@')[0]
except Exception:                                           # noqa: BLE001
    pass
try:
    alvos['senha do RabbitMQ'] = settings.CELERY_BROKER_URL.split(':')[2].split('@')[0]
except Exception:                                           # noqa: BLE001
    pass
for nome, valor in alvos.items():
    if not valor or len(valor) < 6:
        print(f'  {nome}: nao consegui isolar (pulado)')
        continue
    vazou = valor in texto
    print(f'  {nome} em claro no corpo: {vazou}')
    if vazou:
        falhas.append(f'{nome} sai em texto claro no alerta de erro por e-mail')

print('=== 3. um setting NOVO com credencial ja nasce escondido ===')
# O que se verifica aqui e a DECISAO: esconder pelo formato do valor, e nao
# por uma lista de nomes. Um nome novo numa lista e algo que se esquece.
with override_settings(SERVICO_NOVO_DE_MENTIRA='https://usuario:SenhaInventada123@exemplo.invalid/x'):
    novo = corpo()
escondido = 'SenhaInventada123' not in novo
print(f'  credencial de um setting recem-criado escondida: {escondido}')
if not escondido:
    falhas.append(
        'setting novo com credencial embutida na URL sai em claro — a filtragem '
        'voltou a decidir pelo nome em vez do valor'
    )

print('=== 4. termo de busca (nome de paciente) na query string ===')
for rotulo, presente in [
    ('o termo em qualquer lugar do corpo', 'Carlos' in texto),
    ('"?q=" na Request URL', '?q=' in texto),
    ("QUERY_STRING com o valor", "QUERY_STRING = 'q=" in texto),
]:
    print(f'  {rotulo}: {presente}')
    if presente:
        falhas.append(f'o alerta de erro leva o termo de busca ({rotulo})')

print('=== 5. o caminho continua no relatorio ===')
# Suprimir demais tambem e defeito: sem saber QUAL tela estourou, o alerta
# nao serve para nada. O caminho nao carrega dado de paciente — os
# identificadores das rotas de /app/ sao UUID.
tem_caminho = '/app/patients/' in texto
print(f'  o caminho da tela aparece: {tem_caminho}')
if not tem_caminho:
    falhas.append('o alerta perdeu o caminho da tela — nao da para saber o que estourou')

print('=== 6. corpo do POST e variaveis locais seguem suprimidos ===')
post = RequestFactory().post('/app/patients/novo/', {'full_name': 'Carlos Adulto da Silva'})
texto_post = corpo(post)
vazou_post = 'Carlos Adulto da Silva' in texto_post
print(f'  valor enviado no POST aparece: {vazou_post}')
if vazou_post:
    falhas.append('o corpo do POST voltou a aparecer no alerta de erro')

print('---')
if falhas:
    for linha in falhas:
        print('FALHA:', linha)
    raise SystemExit(1)
print('OK: o alerta de erro diz o que estourou sem levar segredo nem dado de paciente.')
