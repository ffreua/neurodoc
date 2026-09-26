"""A fotografia do paciente: quem envia, o que e recusado, e quem alcanca.

Tenta quebrar, nao confirmar. As perguntas sao:

- um PDF renomeado para .png entra?
- um arquivo acima do limite entra?
- a foto de um paciente da clinica B abre para quem esta na clinica A?
- o formulario do cadastro entrega mesmo o arquivo, ou o `enctype` ficou
  para tras e ele some em silencio?
- a secretaria consegue enviar? (cadastro e administrativo, e dela)
- trocar a foto mexe em `row_version` e cria conflito de edicao?
- substituir troca o arquivo, e remover apaga do disco?
"""
import base64
import io
import struct
import zlib
from pathlib import Path

from django.conf import settings as dj_settings
from django.test import Client

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
# O cliente de teste fala HTTP. Com a configuracao de producao carregada,
# `SECURE_SSL_REDIRECT` devolve 301 para tudo, e o roteiro passa a medir o
# redirecionamento em vez da tela que veio conferir -- com as assercoes
# falhando por 301, o que parece defeito no codigo testado. No ambiente
# local, onde `DEBUG=True`, esta linha nao muda nada.
dj_settings.SECURE_SSL_REDIRECT = False

from accounts.models import User
from patients import photo as photo_storage
from patients.models import Patient
from tenancy.models import Membership, Tenant

failures = []
tenant_a = Tenant.objects.get(slug='demo-clinica-a')
tenant_b = Tenant.objects.get(slug='demo-clinica-b')
pa = Patient.objects.filter(tenant=tenant_a, full_name='Carlos Adulto da Silva').first()
pb = Patient.objects.filter(tenant=tenant_b).first()


def png(width=8, height=8, color=b'\xff\x00\x00'):
    """PNG minimo de verdade, montado aqui para nao depender de arquivo no repo."""
    def chunk(tag, data):
        payload = tag + data
        return struct.pack('>I', len(data)) + payload + struct.pack('>I', zlib.crc32(payload))

    raw = b''.join(b'\x00' + color * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def entrar(email):
    """Sessao ja dentro da clinica A, como nos demais roteiros.

    `force_login` mais `tenant_id` na sessao. Passar pelo formulario de
    login funcionaria, mas quem tem vinculo em duas clinicas cai na tela de
    escolha de organizacao, e todo `/app/` responde 302 para la -- o que se
    leria aqui como permissao negada.
    """
    user = User.objects.get(email=email)
    membership = Membership.objects.get(user=user, tenant=tenant_a)
    c = Client()
    c.force_login(user)
    session = c.session
    session['tenant_id'] = str(membership.tenant_id)
    session.save()
    return c


def upload(client, patient, content, nome='foto.png'):
    arquivo = io.BytesIO(content)
    arquivo.name = nome
    return client.post(f'/app/patients/{patient.id}/foto/', {'photo': arquivo}, follow=True)


print('=== 1. o que o validador recusa ===')
casos = [
    ('PDF renomeado para .png', b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n' + b'0' * 2048, True),
    ('arquivo vazio', b'', True),
    ('acima do limite', png() + b'\x00' * (photo_storage.MAX_PHOTO_BYTES + 1), True),
    ('PNG legitimo', png(), False),
]
for rotulo, conteudo, deve_recusar in casos:
    try:
        photo_storage.validate_photo(conteudo)
        recusou = False
    except photo_storage.PhotoRejected:
        recusou = True
    print(f'  {rotulo:32} recusado={recusou}')
    if recusou != deve_recusar:
        failures.append(f'{rotulo}: recusado={recusou}, esperado={deve_recusar}')

print('=== 2. captura da camera ===')
valida = 'data:image/png;base64,' + base64.b64encode(png()).decode()
for rotulo, valor, espera in [
    ('vazio devolve None', '', 'none'),
    ('data URL valida decodifica', valida, 'bytes'),
    ('texto solto e recusado', 'abc', 'erro'),
    ('base64 corrompido e recusado', 'data:image/png;base64,@@@nao@@@', 'erro'),
]:
    try:
        resultado = photo_storage.decode_capture(valor)
        obtido = 'none' if resultado is None else 'bytes'
    except photo_storage.PhotoRejected:
        obtido = 'erro'
    print(f'  {rotulo:32} -> {obtido} ok={obtido == espera}')
    if obtido != espera:
        failures.append(f'decode_capture: {rotulo} devolveu {obtido}, esperado {espera}')

print('=== 3. envio pela rota, por papel ===')
for email, papel in [('doctor-a@demo.neurodoc.local', 'medico/dono'),
                     ('secretary-a@demo.neurodoc.local', 'secretaria')]:
    c = entrar(email)
    r = upload(c, pa, png(color=b'\x00\xff\x00'))
    pa.refresh_from_db()
    gravou = bool(pa.photo_path) and Path(pa.photo_path).is_file()
    print(f'  {papel:14} POST -> {r.status_code}  gravou={gravou}  mime={pa.photo_mime}')
    if r.status_code != 200 or not gravou:
        failures.append(f'{papel} nao conseguiu enviar a fotografia')

print('=== 4. o arquivo servido ===')
c = entrar('doctor-a@demo.neurodoc.local')
r = c.get(f'/app/patients/{pa.id}/foto.img')
print(f'  GET foto.img -> {r.status_code} tipo={r.headers.get("Content-Type")}')
print(f'  Cache-Control={r.headers.get("Cache-Control")}')
print(f'  nosniff={r.headers.get("X-Content-Type-Options")} CSP={bool(r.headers.get("Content-Security-Policy"))}')
if r.status_code != 200:
    failures.append('a fotografia do proprio paciente nao abre')
if r.headers.get('Cache-Control') != 'private, max-age=300':
    failures.append('a fotografia pode cair em cache compartilhado')
if r.headers.get('X-Content-Type-Options') != 'nosniff' or not r.headers.get('Content-Security-Policy'):
    failures.append('a fotografia e servida sem nosniff/CSP')

print('=== 5. paciente de outra clinica ===')
r = c.get(f'/app/patients/{pb.id}/foto.img')
print(f'  GET foto.img do paciente da clinica B -> {r.status_code}')
if r.status_code != 404:
    failures.append(f'a foto de paciente de outra clinica respondeu {r.status_code}, nao 404')
r = upload(c, pb, png())
print(f'  POST foto/ no paciente da clinica B -> {r.status_code}')
if r.status_code != 404:
    failures.append(f'enviar foto para paciente de outra clinica respondeu {r.status_code}, nao 404')

print('=== 6. o formulario do cadastro entrega o arquivo ===')
r = c.get(f'/app/patients/{pa.id}/edit/')
corpo = r.content.decode()
tem_enctype = 'enctype="multipart/form-data"' in corpo
tem_campo = 'name="photo"' in corpo
tem_aviso = 'autoriza' in corpo.lower()
print(f'  enctype={tem_enctype} campo de arquivo={tem_campo} aviso de consentimento={tem_aviso}')
if not tem_enctype:
    failures.append('o formulario perdeu o enctype: o arquivo sumiria em silencio')
if not tem_campo:
    failures.append('o formulario nao tem o campo de fotografia')
if not tem_aviso:
    failures.append('o aviso sobre a autorizacao em papel sumiu da tela')

print('=== 7. substituir troca, e nao acumula ===')
pa.refresh_from_db()
antes = pa.photo_path
upload(c, pa, png(color=b'\x00\x00\xff'), nome='outra.png')
pa.refresh_from_db()
print(f'  mesmo caminho={pa.photo_path == antes} arquivo existe={Path(pa.photo_path).is_file()}')
if not Path(pa.photo_path).is_file():
    failures.append('depois de substituir, o arquivo da fotografia nao existe')

print('=== 8. trocar a foto nao mexe na versao do cadastro ===')
pa.refresh_from_db()
versao_antes = pa.row_version
upload(c, pa, png(color=b'\xff\xff\x00'))
pa.refresh_from_db()
print(f'  row_version {versao_antes} -> {pa.row_version}')
if pa.row_version != versao_antes:
    failures.append('trocar a fotografia incrementou row_version e criaria conflito de edicao')

print('=== 9. remover apaga do disco ===')
caminho = Path(pa.photo_path)
r = c.post(f'/app/patients/{pa.id}/foto/', {'action': 'remove'}, follow=True)
pa.refresh_from_db()
print(f'  POST remove -> {r.status_code} campo limpo={not pa.photo_path} arquivo no disco={caminho.is_file()}')
if pa.photo_path or caminho.is_file():
    failures.append('remover a fotografia deixou o registro ou o arquivo para tras')

print('=== 10. arquivo sumido nao derruba a tela ===')
upload(c, pa, png())
pa.refresh_from_db()
sumido = Path(pa.photo_path)
sumido.unlink()
r_img = c.get(f'/app/patients/{pa.id}/foto.img')
r_ficha = c.get(f'/app/patients/{pa.id}/')
print(f'  foto.img -> {r_img.status_code} (404 esperado)  ficha -> {r_ficha.status_code} (200 esperado)')
if r_img.status_code != 404 or r_ficha.status_code != 200:
    failures.append('arquivo ausente derrubou a leitura em vez de cair para a inicial do nome')

# Limpeza: a fotografia e do banco de demonstracao, nao deste roteiro.
photo_storage.discard_photo(pa)
pa.save(update_fields=photo_storage.PHOTO_FIELDS)

print('---')
if failures:
    for line in failures:
        print('FALHA:', line)
    raise SystemExit(1)
print('OK: a fotografia entra so pelo que vale, e so para quem pode.')
