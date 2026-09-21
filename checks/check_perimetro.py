"""A borda do sistema: o que entra por ela e o que sai por ela.

Tres defeitos deste roteiro vieram de uma auditoria externa em
20/09/2026, e os tres tinham a mesma forma -- codigo correto para um
navegador, rodando onde nao ha navegador nenhum:

- o agente de digitalizacao e um script, nao uma aba, e o `CsrfViewMiddleware`
  recusava a chamada dele antes de a view comecar;
- a desidentificacao trocava **pedacos de palavra** pelo nome do paciente,
  e mandava o texto adulterado ao provedor de IA;
- os limitadores por IP liam `REMOTE_ADDR`, que atras do Traefik e o IP do
  Traefik -- um balde so para o planeta inteiro.

Tenta quebrar. As perguntas sao:

- o agente de captura consegue enviar pagina sem cookie e sem token CSRF?
  e um token de sessao invalido continua sendo recusado?
- a desidentificacao ainda come "Anamnese" quando a paciente se chama Ana?
  e continua escondendo o nome de quem ela deve esconder?
- um cliente consegue escrever o proprio IP no cabecalho e escapar do
  limite? e dois visitantes atras do mesmo proxy caem no mesmo balde?
"""
import uuid

from django.conf import settings as dj_settings
from django.test import Client, RequestFactory

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']

from accounts.models import User
from ai.deidentification import deidentify_text
from base.net import UNKNOWN, client_ip
from integrations import capture
from integrations.models import CaptureDevice, CaptureDeviceStatus, CaptureSession
from patients.models import Patient
from tenancy.models import Membership

TENANT = 'demo-clinica-a'
failures = []


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


user = User.objects.get(email='doctor-a@demo.neurodoc.local')
membership = Membership.objects.get(user=user, tenant__slug=TENANT)
paciente = Patient.objects.filter(tenant_id=membership.tenant_id).first()

print('=== 1. o agente de digitalizacao consegue falar com o sistema ===')
# `enforce_csrf_checks=True`: sem isto o cliente de teste desliga o CSRF e
# o roteiro passaria com o defeito de pe -- que e exatamente por que
# nenhum dos outros 44 roteiros pegou este.
agente = Client(enforce_csrf_checks=True)

device, codigo = capture.initiate_pairing(membership.tenant, f'scanner-{uuid.uuid4().hex[:6]}', membership)
capture.complete_pairing(device, codigo)
device.refresh_from_db()
confere(device.status == CaptureDeviceStatus.PAIRED, 'o aparelho pareia', device.status)

sessao, token = capture.open_session(device, paciente, membership)

pdf = b'%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n'
from django.core.files.uploadedfile import SimpleUploadedFile

resposta = agente.post(
    f'/capture/upload/{token}/',
    {'page_number': '1', 'page': SimpleUploadedFile('p1.pdf', pdf, 'application/pdf')},
)
confere(resposta.status_code == 200,
        'pagina enviada sem cookie e sem token CSRF e aceita', f'HTTP {resposta.status_code}')
if resposta.status_code == 200:
    confere(resposta.json().get('status') == 'received', 'a resposta confirma o recebimento')

# Duplicata: mesmos bytes na mesma sessao nao viram segunda copia.
resposta = agente.post(
    f'/capture/upload/{token}/',
    {'page_number': '2', 'page': SimpleUploadedFile('p1-de-novo.pdf', pdf, 'application/pdf')},
)
confere(resposta.status_code == 409, 'a mesma pagina de novo e recusada', f'HTTP {resposta.status_code}')

# O que autentica e o token, e ele continua valendo: sem CSRF **nao**
# quer dizer sem autenticacao.
resposta = agente.post(
    f'/capture/upload/token-que-nao-existe/',
    {'page_number': '1', 'page': SimpleUploadedFile('p.pdf', pdf, 'application/pdf')},
)
confere(resposta.status_code == 403, 'token de sessao invalido continua recusado',
        f'HTTP {resposta.status_code}')

sessao.refresh_from_db()
confere(sessao.page_count == 1, 'a sessao contou uma pagina', str(sessao.page_count))

print('=== 2. a desidentificacao nao come o vocabulario clinico ===')


class _Paciente:
    cpf = ''
    birth_date = None
    id = None

    def __init__(self, nome, mae=''):
        self.full_name = nome
        self.mother_name = mae


# Cada um destes quebrava antes: a substituicao nao exigia palavra
# inteira, e qualquer parte do nome com tres letras comia o meio das
# outras palavras.
intactos = [
    ('Ana Lima', 'Anamnese dirigida sem alteracoes.', 'Anamnese'),
    ('Dan Costa', 'Sem danos neurologicos evidentes.', 'danos'),
    ('Maria das Gracas', 'Cefaleia em todas as noites.', 'todas'),
    ('Rosa Campos', 'Sem rosacea; pele sem lesoes.', 'rosacea'),
]
for nome, texto, palavra in intactos:
    saida = deidentify_text(texto, _Paciente(nome))
    confere(palavra in saida, f'paciente {nome!r} nao corrompe {palavra!r}', saida)

# E o essencial: ela continua escondendo quem deve.
saida = deidentify_text(
    'Ana Lima compareceu. LIMA assinou. CPF 123.456.789-01, (11) 98888-7777, a@b.com',
    _Paciente('Ana Lima'),
)
confere('Ana' not in saida and 'Lima' not in saida and 'LIMA' not in saida,
        'o nome do paciente sai, em qualquer caixa', saida[:44])
confere('[CPF]' in saida and '[TELEFONE]' in saida and '[EMAIL]' in saida,
        'CPF, telefone e e-mail continuam saindo')

saida = deidentify_text('Filha de Rita Pereira, sem intercorrencias.', _Paciente('Ana Lima', 'Rita Pereira'))
confere('Rita' not in saida and 'Pereira' not in saida,
        'o nome da mae sai', saida)

print('=== 3. o IP do visitante atravessa o proxy, e so o nosso ===')
rf = RequestFactory()


def pede(remoto, xff=None):
    extra = {'REMOTE_ADDR': remoto}
    if xff is not None:
        extra['HTTP_X_FORWARDED_FOR'] = xff
    return rf.get('/', **extra)


casos = [
    ('cliente direto, sem proxy', '203.0.113.9', None, '203.0.113.9'),
    # O ataque: quem fala direto com o app escreve o que quiser no
    # cabecalho. Acreditar nele seria trocar o limite por um enfeite.
    ('cliente direto tentando forjar', '203.0.113.9', '1.2.3.4', '203.0.113.9'),
    ('atras do proxy nosso', '10.0.1.5', '203.0.113.9', '203.0.113.9'),
    ('atras do proxy, com XFF forjado antes', '10.0.1.5', '1.2.3.4, 203.0.113.9', '203.0.113.9'),
    ('dois proxies nossos na cadeia', '10.0.1.5', '203.0.113.9, 10.0.1.9', '203.0.113.9'),
    ('cadeia inteiramente interna', '10.0.1.5', '10.0.1.2, 10.0.1.9', '10.0.1.2'),
    ('proxy confiavel que nao mandou XFF', '172.18.0.7', None, '172.18.0.7'),
    ('cabecalho com espacos e vazios', '10.0.1.5', '  , 203.0.113.9 ,  ', '203.0.113.9'),
    ('sem endereco nenhum', '', None, UNKNOWN),
]
for nome, remoto, xff, esperado in casos:
    obtido = client_ip(pede(remoto, xff))
    confere(obtido == esperado, nome, f'{obtido!r} (esperado {esperado!r})')

# Dois visitantes atras do mesmo proxy nao podem cair no mesmo balde --
# era isso que fechava a verificacao de receita para todo mundo quando um
# visitante qualquer esgotava a cota.
primeiro = client_ip(pede('10.0.1.5', '198.51.100.1'))
segundo = client_ip(pede('10.0.1.5', '198.51.100.2'))
confere(primeiro != segundo,
        'dois visitantes pelo mesmo proxy sao dois IPs', f'{primeiro} != {segundo}')

print('=== 4. ninguem voltou a ler REMOTE_ADDR por conta propria ===')
from pathlib import Path

raiz = Path(dj_settings.BASE_DIR)
reincidentes = []
for caminho in raiz.rglob('*.py'):
    partes = set(caminho.parts)
    if partes & {'.venv', '__pycache__', 'migrations', 'checks'}:
        continue
    if caminho.name == 'net.py' and caminho.parent.name == 'base':
        continue
    if 'REMOTE_ADDR' in caminho.read_text(encoding='utf-8', errors='replace'):
        reincidentes.append(str(caminho.relative_to(raiz)))
confere(not reincidentes,
        'so `base/net.py` toca em REMOTE_ADDR', ', '.join(reincidentes))

print('=== 5. o navegador nao guarda tela de prontuario ===')
# Sem `Cache-Control`, o navegador aplica cache heuristico e o botao
# Voltar reexibe a pagina depois do logout -- num computador de
# consultorio, a lista de pacientes do medico anterior para quem sentar
# depois. `Vary: Cookie` resolve o cache compartilhado e nao resolve o
# historico do navegador.
from accounts.models import User as _User
from tenancy.models import Tenant as _Tenant

_medico = _User.objects.filter(email='doctor-a@demo.neurodoc.local').first()
_clinica = _Tenant.objects.filter(slug='demo-clinica-a').first()
if _medico is None or _clinica is None:
    print('  (sem a clinica de demonstracao; secao pulada)')
else:
    _c = Client()
    _c.force_login(_medico)
    _s = _c.session
    _s['tenant_id'] = str(_clinica.id)
    _s.save()
    for _rota in ['/app/reporting/', '/app/patients/', '/app/scheduling/']:
        _r = _c.get(_rota)
        _cc = _r.headers.get('Cache-Control', '')
        print(f'  {_rota:24} HTTP {_r.status_code}  Cache-Control={_cc!r}')
        if _r.status_code == 200 and 'no-store' not in _cc:
            failures.append(f'{_rota} pode ficar no cache do navegador')
    # A foto do paciente continua com a politica propria: sobrescreve-la
    # faria o navegador rebaixar a mesma imagem a cada rolagem da lista.
    from patients.models import Patient as _Patient

    _p = _Patient.objects.filter(tenant=_clinica).exclude(photo_path='').first()
    if _p is not None:
        _r = _c.get(f'/app/patients/{_p.id}/foto.img')
        _cc = _r.headers.get('Cache-Control', '')
        print(f'  foto do paciente         HTTP {_r.status_code}  Cache-Control={_cc!r}')
        if _r.status_code == 200 and 'max-age=300' not in _cc:
            failures.append('a politica propria da foto do paciente foi sobrescrita')
    else:
        print('  (nenhum paciente com foto; a excecao nao foi exercitada)')

print('=== limpeza ===')
# Ordem obrigatoria: o registro de proveniencia prende a sessao
# (`CaptureUploadRecord.session` e PROTECT) e prende o anexo, e o anexo
# tem arquivo no volume de midia. Sem isto, cada rodada deixava a pagina
# de teste no prontuario do paciente de demonstracao.
from pathlib import Path

from documents.models import Attachment
from integrations.models import CaptureUploadRecord

anexos = list(
    CaptureUploadRecord.objects.filter(session=sessao)
    .values_list('attachment_id', flat=True)
)
CaptureUploadRecord.objects.filter(session=sessao).delete()
for att in Attachment.objects.filter(id__in=anexos):
    if att.storage_key:
        Path(att.storage_key).unlink(missing_ok=True)
Attachment.objects.filter(id__in=anexos).delete()
CaptureSession.objects.filter(id=sessao.id).delete()
CaptureDevice.objects.filter(id=device.id).delete()
print(f'  removidos: 1 sessao, 1 aparelho, {len(anexos)} pagina(s) digitalizada(s)')

print()
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o agente entra, o texto sai limpo e o IP do visitante e o dele.')
