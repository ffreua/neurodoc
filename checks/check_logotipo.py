"""O logotipo que o navegador guarda e o da clinica aberta.

Este roteiro existe por um defeito encontrado em producao: a secretaria
que atende em duas clinicas trocava de organizacao, o nome no menu mudava
e **o logotipo continuava o da clinica anterior**. Parecia vazamento
entre inquilinos e nao era -- o servidor sempre mandou a imagem certa. O
que vazava era o cache do navegador.

A causa e uma propriedade so: `/app/org/clinica/logotipo.img` e o **mesmo
endereco** para todas as clinicas, e o que ele devolve depende do
`tenant_id` que esta na sessao. O cache do navegador guarda por URL e por
`Vary`; o `Vary: Cookie` da sessao nao separa nada porque trocar de
organizacao escreve na mesma sessao e **nao troca o cookie**. Com
`Cache-Control: private, max-age=300`, que foi o que esteve no ar, havia
cinco minutos em que a imagem da clinica anterior era servida de dentro
do proprio navegador, sem pergunta nenhuma ao servidor.

O roteiro confere a correcao pelo comportamento e nao pela redacao do
cabecalho: ele faz a troca de organizacao, devolve o validador antigo em
`If-None-Match` -- que e literalmente o que o navegador faz -- e exige
que a resposta seja a imagem nova.
"""
import re
import struct
import zlib
from pathlib import Path

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# Ver o comentario igual em `check_g3`: com a configuracao de producao
# carregada, `SECURE_SSL_REDIRECT` devolve 301 para tudo e o roteiro passa
# a medir o redirecionamento em vez da tela.
dj_settings.SECURE_SSL_REDIRECT = False

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import NoReverseMatch, reverse

from accounts.models import User
from tenancy.models import ClinicProfile, Membership

TENANT_A = 'demo-clinica-a'
TENANT_B = 'demo-clinica-b'
LOGO_URL = '/app/org/clinica/logotipo.img'
SECRETARIA = 'secretary-a@demo.neurodoc.local'
DONO = 'doctor-a@demo.neurodoc.local'
failures = []


def png_bytes(cor, width=8, height=8):
    """PNG minimo valido, montado a mao para nao depender de arquivo externo.

    A cor e parametro porque este roteiro precisa de **duas** imagens
    diferentes: com o mesmo PNG nas duas clinicas, o defeito que se vem
    conferir -- servir a imagem errada -- passaria despercebido.
    """
    raw = b''.join(b'\x00' + cor * width for _ in range(height))

    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def entrar(email, slug):
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant__slug=slug)
    c = Client()
    c.force_login(user)
    s = c.session
    s['tenant_id'] = str(membership.tenant_id)
    s.save()
    return c


def trocar(client, email, slug):
    """Troca de organizacao como o produto troca: mesma sessao, mesmo cookie.

    Nao se cria um `Client` novo aqui, de proposito. Cliente novo tem
    cookie novo, e cookie novo e exatamente o que o navegador **nao** tem
    quando a secretaria clica em Trocar organizacao -- montar o cenario
    assim esconderia o defeito que o roteiro veio conferir.
    """
    membership = Membership.objects.get(user__email=email, tenant__slug=slug)
    s = client.session
    s['tenant_id'] = str(membership.tenant_id)
    s.save()
    return client


print('=== 1. cada clinica com o seu logotipo ===')
logo_a = png_bytes(b'\xff\x00\x00')
logo_b = png_bytes(b'\x00\x00\xff', width=10, height=10)
for slug, conteudo in ((TENANT_A, logo_a), (TENANT_B, logo_b)):
    dono = entrar(DONO, slug)
    r = dono.post('/app/org/clinica/logotipo/', {
        'logo': SimpleUploadedFile('logo.png', conteudo, content_type='image/png'),
    }, follow=True)
    perfil = ClinicProfile.objects.get(tenant__slug=slug)
    print(f'  {slug}: HTTP {r.status_code} | bytes gravados: {perfil.logo_bytes}')
    if perfil.logo_bytes != len(conteudo):
        failures.append(f'o logotipo de {slug} nao foi gravado')

caminhos = {
    p.tenant.slug: p.logo_path
    for p in ClinicProfile.objects.select_related('tenant').filter(
        tenant__slug__in=[TENANT_A, TENANT_B],
    )
}
print('  arquivos em disco:', len(set(caminhos.values())), 'caminho(s) distinto(s)')
if len(set(caminhos.values())) != 2:
    failures.append('as duas clinicas apontam para o mesmo arquivo de logotipo')

print('=== 2. a mesma sessao, trocando de organizacao ===')
sessao = entrar(SECRETARIA, TENANT_A)
na_a = sessao.get(LOGO_URL)
etag_a = na_a.headers.get('ETag')
print(f'  na clinica A: HTTP {na_a.status_code} | {len(na_a.content)} bytes'
      f' | ETag {etag_a!r} | Cache-Control {na_a.headers.get("Cache-Control")!r}')
if na_a.content != logo_a:
    failures.append('a clinica A nao recebeu o proprio logotipo')

trocar(sessao, SECRETARIA, TENANT_B)
na_b = sessao.get(LOGO_URL)
etag_b = na_b.headers.get('ETag')
print(f'  na clinica B: HTTP {na_b.status_code} | {len(na_b.content)} bytes'
      f' | ETag {etag_b!r}')
if na_b.content != logo_b:
    failures.append('a clinica B recebeu o logotipo da clinica A')
if not etag_a or not etag_b:
    failures.append('a resposta do logotipo nao traz validador (ETag)')
elif etag_a == etag_b:
    failures.append(
        'o validador e o mesmo nas duas clinicas: o navegador tratara as duas '
        'imagens como a mesma entrada de cache',
    )

print('=== 3. o navegador perguntando com o validador da clinica anterior ===')
# Este e o defeito, reproduzido: a imagem da clinica A esta no cache, a
# secretaria trocou para a B, e o navegador revalida com o que tem.
# Responder 304 aqui e mandar o navegador exibir a clinica errada.
revalida = sessao.get(LOGO_URL, HTTP_IF_NONE_MATCH=etag_a or '"nenhum"')
print(f'  If-None-Match com o ETag de A, sessao na B -> HTTP {revalida.status_code}')
if revalida.status_code == 304:
    failures.append(
        'revalidar com o ETag da outra clinica devolveu 304: o navegador '
        'continuaria exibindo o logotipo da clinica anterior',
    )
elif revalida.content != logo_b:
    failures.append('a revalidacao na clinica B nao devolveu o logotipo da B')

# E o outro lado: a correcao nao pode ter virado "baixar tudo de novo a
# cada tela". Um logotipo real tem centenas de quilobytes e aparece no
# menu de toda pagina de `/app/`.
mesma = sessao.get(LOGO_URL, HTTP_IF_NONE_MATCH=etag_b or '"nenhum"')
print(f'  If-None-Match com o ETag da propria clinica -> HTTP {mesma.status_code}')
if mesma.status_code != 304:
    failures.append(
        f'revalidar sem mudanca devolveu {mesma.status_code} em vez de 304: o '
        'logotipo seria rebaixado inteiro em toda tela',
    )

print('=== 4. trocar o logotipo aparece na hora ===')
dono_b = entrar(DONO, TENANT_B)
novo = png_bytes(b'\x00\xff\x00', width=12, height=12)
dono_b.post('/app/org/clinica/logotipo/', {
    'logo': SimpleUploadedFile('logo.png', novo, content_type='image/png'),
}, follow=True)
depois = sessao.get(LOGO_URL, HTTP_IF_NONE_MATCH=etag_b or '"nenhum"')
print(f'  apos a troca, If-None-Match antigo -> HTTP {depois.status_code}')
if depois.status_code == 304 or depois.content != novo:
    failures.append('o logotipo trocado nao chega a quem tem o anterior em cache')

print('=== 5. URL que nao distingue o que serve nao tem prazo fixo ===')
# A regra, escrita uma vez: um endereco so pode ficar guardado por tempo
# fixo quando a propria URL diz o que ele devolve. A foto do paciente
# carrega o id na rota e por isso pode; o logotipo nao carrega nada e por
# isso nao pode. A varredura **procura** `max-age` novo no codigo em vez
# de conferir uma lista escrita a mao, que e o que envelhece.
COM_PRAZO_JUSTIFICADO = {
    'patients/views.py': 'a rota da foto carrega <uuid:patient_id>',
}
raiz = Path(dj_settings.BASE_DIR)
achados = set()
for arquivo in sorted(raiz.rglob('*.py')):
    rel = arquivo.relative_to(raiz).as_posix()
    if rel.startswith(('.venv/', 'checks/')):
        continue
    texto = arquivo.read_text(encoding='utf-8', errors='ignore')
    if not re.search(r'Cache-Control.{0,40}max-age=[1-9]', texto, re.S):
        continue
    achados.add(rel)
    motivo = COM_PRAZO_JUSTIFICADO.get(rel)
    print(f'  {rel}: {motivo or "NAO JUSTIFICADO"}')
    if motivo is None:
        failures.append(
            f'{rel} serve com prazo fixo de cache sem constar da lista deste '
            'roteiro: se a URL nao distingue o que devolve, o prazo mostra a '
            'coisa errada depois de trocar de organizacao',
        )

# A lista tambem envelhece para o outro lado: entrada que nao corresponde
# mais a nada no codigo e justificativa sobrevivendo ao que ela
# justificava, e e assim que a proxima passa despercebida.
sobrando = sorted(set(COM_PRAZO_JUSTIFICADO) - achados)
if sobrando:
    print('  entradas sem correspondencia no codigo:', ', '.join(sobrando))
    failures.append(
        f'{", ".join(sobrando)} consta da lista de prazo justificado e nao serve '
        'mais com prazo fixo: a lista precisa acompanhar o codigo',
    )

cabecalho = sessao.get(LOGO_URL).headers.get('Cache-Control', '')
print(f'  logotipo -> Cache-Control {cabecalho!r}')
if re.search(r'max-age=[1-9]', cabecalho) or 'no-cache' not in cabecalho:
    failures.append(
        f'o logotipo volta com Cache-Control {cabecalho!r}: sem revalidacao, a '
        'troca de organizacao nao troca a imagem',
    )
if 'private' not in cabecalho:
    failures.append('o logotipo pode ficar em cache compartilhado')

print('=== 6. nenhum template remenda o cache por conta propria ===')
# A alternativa recusada: por `?v=` na URL do logotipo. Funciona na tela
# que lembrou e some na proxima -- foi assim que a tela de identidade
# ficou certa e o menu, errado, pelo tempo todo em que o defeito existiu.
remendos = sorted({
    template.relative_to(raiz).as_posix()
    for template in (raiz / 'templates').rglob('*.html')
    for linha in template.read_text(encoding='utf-8', errors='ignore').splitlines()
    if 'clinic-logo-file' in linha and '%}?' in linha
})
print('  templates com bustador proprio:', remendos or 'nenhum')
if remendos:
    failures.append(
        f'{", ".join(remendos)} remenda o cache do logotipo na URL: a correcao '
        'tem de estar na resposta, onde nao da para esquecer dela',
    )

print('=== 7. a fronteira continua de pe ===')
# O cache nao pode ter sido consertado abrindo o endereco: quem nao tem
# vinculo com a clinica da sessao nao ve logotipo nenhum, e a rota
# continua sem aceitar id de organizacao.
anonimo = Client()
r = anonimo.get(LOGO_URL)
print('  sem sessao ->', r.status_code)
if r.status_code == 200:
    failures.append('o logotipo e servido sem sessao')

# `reverse` sem argumento nenhum: se a rota passar a exigir um, isto
# estoura em `NoReverseMatch` -- que e exatamente a resposta que se quer.
try:
    endereco = reverse('tenancy:clinic-logo-file')
except NoReverseMatch as exc:
    endereco = None
    print('  a rota passou a exigir argumento:', exc)
    failures.append(
        'a rota do logotipo passou a aceitar parametro: um endereco que recebe '
        'id de clinica enumera o logotipo de toda a instalacao',
    )
else:
    print('  endereco da rota:', endereco)
    if endereco != LOGO_URL:
        failures.append(f'o endereco do logotipo mudou para {endereco}')

print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for f in failures:
        print(' -', f)
    raise SystemExit(1)
print('OK - o logotipo servido e sempre o da organizacao aberta.')
