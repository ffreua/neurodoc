"""A borda do sistema: o que entra por ela e o que sai por ela.

Dois defeitos deste roteiro vieram de uma auditoria externa em
20/09/2026, e os dois tinham a mesma forma -- uma borda de seguranca
interpretada de modo permissivo demais:

- a desidentificacao trocava **pedacos de palavra** pelo nome do paciente,
  e mandava o texto adulterado ao provedor de IA;
- os limitadores por IP liam `REMOTE_ADDR`, que atras do Traefik e o IP do
  Traefik -- um balde so para o planeta inteiro.

Tenta quebrar. As perguntas sao:

- a desidentificacao ainda come "Anamnese" quando a paciente se chama Ana?
  e continua escondendo o nome de quem ela deve esconder?
- um cliente consegue escrever o proprio IP no cabecalho e escapar do
  limite? e dois visitantes atras do mesmo proxy caem no mesmo balde?
"""
from django.conf import settings as dj_settings
from django.test import Client, RequestFactory

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from ai.deidentification import deidentify_text
from base.net import UNKNOWN, client_ip

failures = []


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


print('=== 1. a desidentificacao nao come o vocabulario clinico ===')


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

print('=== 2. o IP do visitante atravessa o proxy, e so o nosso ===')
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

print('=== 3. ninguem voltou a ler REMOTE_ADDR por conta propria ===')
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

print('=== 4. o navegador nao guarda tela de prontuario ===')
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

print()
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: o texto sai desidentificado, o IP do visitante e o dele e telas clinicas nao ficam no cache.')
