"""A cópia dos backups no Cloudflare R2 aguenta o que dá errado?

`ops/nuvem.py` (2026-11-18) leva cada pasta de backup ao R2 logo depois do
backup. O que ela não pode fazer é **dizer que copiou quando não copiou**:
o SSD ficou 40 dias desconectado sem ninguém ver, e uma cópia na nuvem que
falhasse calada repetiria o caso com mais confiança. Por isso o roteiro
fala com um R2 falso que se comporta como o de verdade nos pontos que
importam -- recusa corpo que não bate com o hash assinado, recusa
sobrescrever objeto travado -- e tenta quebrar:

- a assinatura SigV4 confere com os exemplos da documentação da AWS?
- desligada por padrão; meio configurada é erro, não "desligada";
- endpoint que não é do R2, balde inválido, credencial com permissão
  aberta, com link ou mal colada são recusados sem repetir o segredo;
- a pasta sobe inteira, com `COMPLETE` por último, e ganha a marca sem
  mudar a data que a retenção do backup lê;
- a repetição não reenvia; o envio que caiu no meio retoma;
- objeto diferente já no R2, arquivo local que não bate com o manifesto e
  servidor que corrompe o que guardou viram erro, sem marca;
- a falha de rede é tentada de novo e, persistindo, vira erro;
- o download confere cada arquivo com o manifesto;
- o `backup.sh` chama o envio depois do backup e sai com erro se ele falha,
  e o vigia cobra a marca quando a cópia está ligada.
"""
import hashlib
import http.client
import http.server
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from django.conf import settings as dj_settings

from ops import nuvem

failures = []
ROOT = Path(dj_settings.BASE_DIR)


def confere(condicao, descricao, detalhe=''):
    marca = 'ok  ' if condicao else 'FALHA'
    sufixo = f' ({detalhe})' if detalhe else ''
    print(f'  {marca} {descricao}{sufixo}')
    if not condicao:
        failures.append(descricao)


def levanta(funcao, trecho):
    try:
        funcao()
    except nuvem.ErroNuvem as exc:
        return trecho in str(exc), str(exc)
    return False, 'não levantou'


print('=== 1. a assinatura SigV4 confere com a documentação da AWS ===')
CHAVE_AWS, SEGREDO_AWS = 'AKIAIOSFODNN7EXAMPLE', 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
cab = {'host': 'examplebucket.s3.amazonaws.com', 'range': 'bytes=0-9',
       'x-amz-content-sha256': nuvem.HASH_VAZIO, 'x-amz-date': '20130524T000000Z'}
assinatura = nuvem.assinar('GET', '/test.txt', {}, cab, nuvem.HASH_VAZIO,
                           CHAVE_AWS, SEGREDO_AWS, regiao='us-east-1')
confere(assinatura.endswith(
    'f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'),
    'exemplo GET Object')
cab = {'host': 'examplebucket.s3.amazonaws.com', 'x-amz-content-sha256': nuvem.HASH_VAZIO,
       'x-amz-date': '20130524T000000Z'}
assinatura = nuvem.assinar('GET', '/', {'max-keys': '2', 'prefix': 'J'}, cab,
                           nuvem.HASH_VAZIO, CHAVE_AWS, SEGREDO_AWS, regiao='us-east-1')
confere(assinatura.endswith(
    '34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7'),
    'exemplo List Objects, com consulta')

print('=== 2. configuração: desligada, meio configurada, recusas ===')
temporario = Path(tempfile.mkdtemp(prefix='nuvem-'))
credenciais = temporario / 'r2.env'
CHAVE_ID, SEGREDO = 'a' * 32, 'b' * 64
credenciais.write_text(f'R2_ACCESS_KEY_ID={CHAVE_ID}\nR2_SECRET_ACCESS_KEY={SEGREDO}\n')
credenciais.chmod(0o600)
ENDPOINT = 'https://' + '0123456789abcdef' * 2 + '.r2.cloudflarestorage.com'
base = {'BACKUP_R2_ENDPOINT': ENDPOINT, 'BACKUP_R2_BUCKET': 'neurodoc-backups',
        'BACKUP_R2_CREDENTIALS': str(credenciais)}
confere(nuvem.configurar({}) is None, 'sem as chaves: desligada')
confere(nuvem.configurar({k: '' for k in base}) is None, 'chaves vazias: desligada')
exemplo = (ROOT / '.env.example').read_text(encoding='utf-8')
confere(all(re.search(rf'^{k}=\s*$', exemplo, re.M) for k in base),
        'o .env.example traz as três vazias (o deploy herda o molde)')
for faltando in base:
    parcial = {k: v for k, v in base.items() if k != faltando}
    ok, msg = levanta(lambda: nuvem.configurar(parcial), 'vão juntos')
    confere(ok, f'sem {faltando}: erro, não desligada', msg)
for ruim in ('https://s3.amazonaws.com', 'http://' + ENDPOINT[8:],
             ENDPOINT + '.evil.example', 'https://abc.r2.cloudflarestorage.com'):
    ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_ENDPOINT': ruim}),
                      'BACKUP_R2_ENDPOINT')
    confere(ok, f'endpoint recusado: {ruim[:40]}', msg)
ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_BUCKET': 'Balde_Errado'}),
                  'BACKUP_R2_BUCKET')
confere(ok, 'balde inválido recusado', msg)
for balde in ('prontdoc-backups', 'backups-pront-doc'):
    ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_BUCKET': balde}), 'ProntDoc')
    confere(ok, f'balde do ProntDoc recusado: {balde}', msg)
confere(isinstance(nuvem.configurar(base), nuvem.Nuvem), 'configurada: devolve a Nuvem')
credenciais.chmod(0o644)
ok, msg = levanta(lambda: nuvem.configurar(base), 'modo 600')
confere(ok, 'credencial legível por outros recusada', msg)
credenciais.chmod(0o600)
link = temporario / 'link.env'
link.symlink_to(credenciais)
ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_CREDENTIALS': str(link)}),
                  'sem link')
confere(ok, 'credencial por link recusada', msg)
ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_CREDENTIALS': 'r2.env'}),
                  'absoluto')
confere(ok, 'caminho relativo recusado', msg)
mal = temporario / 'mal.env'
mal.write_text(f'R2_ACCESS_KEY_ID={CHAVE_ID}\nR2_SECRET_ACCESS_KEY=chave com espaco\n')
mal.chmod(0o600)
ok, msg = levanta(lambda: nuvem.configurar({**base, 'BACKUP_R2_CREDENTIALS': str(mal)}),
                  'mal colado')
confere(ok and 'chave com espaco' not in msg, 'segredo mal colado recusado sem repeti-lo', msg)


print('=== 3. um R2 falso que confere hash e trava objetos ===')


class R2Falso(http.server.BaseHTTPRequestHandler):
    objetos = {}       # chave -> (bytes, sha256 da metadata)
    pedidos = []
    falhar_put = set()  # chaves cujo próximo PUT derruba a conexão
    corromper = set()   # chaves que o servidor guarda alteradas
    recusar_tudo = False

    def log_message(self, *args):
        pass

    def _chave(self):
        caminho = self.path.split('?', 1)[0]
        return caminho.split('/', 2)[2] if caminho.count('/') >= 2 else ''

    def _autorizado(self):
        return self.headers.get('Authorization', '').startswith(
            f'AWS4-HMAC-SHA256 Credential={CHAVE_ID}/')

    def do_HEAD(self):
        R2Falso.pedidos.append(('HEAD', self._chave()))
        if R2Falso.recusar_tudo:
            self.send_response(503)
            self.end_headers()
            return
        guardado = R2Falso.objetos.get(self._chave())
        if not guardado:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(guardado[0])))
        self.send_header('x-amz-meta-sha256', guardado[1])
        self.send_header('ETag', '"%s"' % hashlib.md5(guardado[0]).hexdigest())
        self.end_headers()

    def do_PUT(self):
        chave = self._chave()
        R2Falso.pedidos.append(('PUT', chave))
        corpo = self.rfile.read(int(self.headers['Content-Length']))
        if chave in R2Falso.falhar_put:
            R2Falso.falhar_put.discard(chave)
            self.connection.close()
            return
        if not self._autorizado():
            codigo, resposta = 403, b'<Error><Code>AccessDenied</Code></Error>'
        elif hashlib.sha256(corpo).hexdigest() != self.headers['x-amz-content-sha256']:
            codigo, resposta = 400, b'<Error><Code>BadDigest</Code></Error>'
        elif chave in R2Falso.objetos:
            # A trava do balde: objeto gravado não se sobrescreve.
            codigo, resposta = 403, b'<Error><Code>ObjectLockedByBucketPolicy</Code></Error>'
        else:
            if chave in R2Falso.corromper:
                corpo = corpo[:-1] + bytes([corpo[-1] ^ 1])
            R2Falso.objetos[chave] = (corpo, self.headers.get('x-amz-meta-sha256', ''))
            codigo, resposta = 200, b''
        self.send_response(codigo)
        self.send_header('Content-Length', str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def do_GET(self):
        guardado = R2Falso.objetos.get(self._chave())
        corpo = guardado[0] if guardado else b'<Error><Code>NoSuchKey</Code></Error>'
        self.send_response(200 if guardado else 404)
        self.send_header('Content-Length', str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)


servidor = http.server.ThreadingHTTPServer(('127.0.0.1', 0), R2Falso)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
porta = servidor.server_address[1]
nuvem.time.sleep = lambda segundos: None  # as esperas entre tentativas, sem esperar
r2 = nuvem.Nuvem('falso', 'neurodoc-backups', CHAVE_ID, SEGREDO,
                 conexao=lambda: http.client.HTTPConnection('127.0.0.1', porta, timeout=10))


def criar_backup(raiz, nome, dias_atras=0):
    pasta = raiz / nome
    pasta.mkdir(parents=True)
    arquivos = {'database.dump.age': os.urandom(300_000), 'media.tar.age': os.urandom(2_000_000),
                'signing.tar.age': os.urandom(500), 'letsencrypt.tar.age': os.urandom(800)}
    for nome_arquivo, dados in arquivos.items():
        (pasta / nome_arquivo).write_bytes(dados)
    manifesto = {'files': {n: {'sha256': hashlib.sha256(d).hexdigest(), 'bytes': len(d)}
                           for n, d in arquivos.items()}}
    (pasta / 'manifest.json').write_text(json.dumps(manifesto))
    (pasta / 'COMPLETE').write_text('ok\n')
    antigo = time.time() - dias_atras * 86400
    os.utime(pasta, (antigo, antigo))
    return pasta


raiz = temporario / 'neurodoc-backups'
velha = criar_backup(raiz, '20261020T060000Z-aaaaaaaa', dias_atras=29)
nova = criar_backup(raiz, '20261118T060000Z-bbbbbbbb')
incompleta = criar_backup(raiz, '20261118T070000Z-cccccccc')
(incompleta / 'COMPLETE').unlink()
(raiz / 'nao-e-backup').mkdir()
confere(nuvem.pastas_pendentes(raiz) == [velha, nova],
        'pendentes: só as completas, com nome de backup, em ordem')

print('=== 4. a pasta sobe inteira, COMPLETE por último, data preservada ===')
data_antes = velha.stat().st_mtime
R2Falso.pedidos.clear()
enviados = nuvem.enviar_pasta(r2, velha)
confere(enviados == 6, 'seis arquivos enviados', str(enviados))
puts = [c for m, c in R2Falso.pedidos if m == 'PUT']
confere(puts[-1] == f'{velha.name}/COMPLETE' and puts[-2] == f'{velha.name}/manifest.json',
        'manifest.json e COMPLETE por último', str(puts[-2:]))
confere(all(R2Falso.objetos[f'{velha.name}/{p.name}'][0] == p.read_bytes()
            for p in velha.iterdir() if p.name != nuvem.MARCA), 'bytes idênticos no R2')
confere((velha / nuvem.MARCA).is_file(), 'a pasta ganhou a marca')
confere(abs(velha.stat().st_mtime - data_antes) < 1,
        'a data da pasta (que a retenção lê) não mudou',
        f'{(velha.stat().st_mtime - data_antes):.0f}s')
confere(nuvem.pastas_pendentes(raiz) == [nova], 'a enviada saiu das pendentes')

print('=== 5. repetição não reenvia; envio que caiu no meio retoma ===')
(velha / nuvem.MARCA).unlink()
R2Falso.pedidos.clear()
confere(nuvem.enviar_pasta(r2, velha) == 0, 'repetir a mesma pasta: nada reenviado')
confere(not any(m == 'PUT' for m, _ in R2Falso.pedidos), 'nenhum PUT na repetição')
R2Falso.falhar_put = {f'{nova.name}/media.tar.age'}
enviados = nuvem.enviar_pasta(r2, nova)
confere(enviados == 6, 'a queda da conexão no PUT é tentada de novo e passa', str(enviados))

print('=== 6. o que não pode virar "copiado" ===')
outra = criar_backup(raiz, '20261117T060000Z-dddddddd')
R2Falso.objetos[f'{outra.name}/database.dump.age'] = (b'outro conteudo', 'x' * 64)
ok, msg = levanta(lambda: nuvem.enviar_pasta(r2, outra), 'outro conteúdo')
confere(ok and not (outra / nuvem.MARCA).exists(),
        'objeto diferente já no R2: erro e sem marca', msg)
del R2Falso.objetos[f'{outra.name}/database.dump.age']
(outra / 'signing.tar.age').write_bytes(b'adulterado')
ok, msg = levanta(lambda: nuvem.enviar_pasta(r2, outra), 'não confere com o manifesto')
confere(ok and not (outra / nuvem.MARCA).exists(),
        'arquivo local fora do manifesto: não envia e sem marca', msg)
corrompida = criar_backup(raiz, '20261116T060000Z-eeeeeeee')
R2Falso.corromper = {f'{corrompida.name}/media.tar.age'}
ok, msg = levanta(lambda: nuvem.enviar_pasta(r2, corrompida), 'não confere')
confere(ok and not (corrompida / nuvem.MARCA).exists(),
        'o R2 guardou diferente do enviado: o ETag (MD5) acusa e sem marca', msg)
R2Falso.corromper = set()
sem_hash = nuvem.Nuvem('falso', 'neurodoc-backups', CHAVE_ID, SEGREDO,
                       conexao=r2.conexao)
original_enviar = nuvem.Nuvem.enviar


def enviar_com_hash_errado(self, chave, arquivo, sha, tamanho):
    with arquivo.open('rb') as corpo:
        status, _, dados = self._pedir('PUT', chave, corpo=corpo, tamanho=tamanho,
                                       hash_corpo='0' * 64, extras={'x-amz-meta-sha256': sha})
    if status != 200:
        raise nuvem.ErroNuvem(f'PUT {chave}: {status} {nuvem.codigo_de_erro(dados)}')


nuvem.Nuvem.enviar = enviar_com_hash_errado
ultima = criar_backup(raiz, '20261115T060000Z-ffffffff')
ok, msg = levanta(lambda: nuvem.enviar_pasta(sem_hash, ultima), 'BadDigest')
confere(ok, 'corpo que não bate com o hash assinado: recusado pelo servidor', msg)
nuvem.Nuvem.enviar = original_enviar
R2Falso.recusar_tudo = True
ok, msg = levanta(lambda: nuvem.enviar_pasta(r2, ultima), f'falhou {nuvem.TENTATIVAS} vezes')
confere(ok, 'servidor fora do ar: tentado de novo e, persistindo, erro', msg)
R2Falso.recusar_tudo = False
errada = nuvem.Nuvem('falso', 'neurodoc-backups', 'c' * 32, SEGREDO, conexao=r2.conexao)
ok, msg = levanta(lambda: errada.enviar(f'{ultima.name}/COMPLETE', ultima / 'COMPLETE',
                                        nuvem.sha256_de(ultima / 'COMPLETE'), 3),
                  'AccessDenied')
confere(ok and SEGREDO not in msg, 'chave errada: AccessDenied, sem o segredo na mensagem', msg)

print('=== 7. o download confere com o manifesto ===')
destino = temporario / 'baixados'
final = nuvem.baixar_pasta(r2, nova.name, destino)
confere(all((final / p.name).read_bytes() == p.read_bytes()
            for p in nova.iterdir() if p.name != nuvem.MARCA), 'baixado igual ao original')
ok, msg = levanta(lambda: nuvem.baixar_pasta(r2, nova.name, destino), 'já existe')
confere(ok, 'não sobrescreve download anterior', msg)
R2Falso.objetos[f'{velha.name}/media.tar.age'] = (b'trocado', '')
ok, msg = levanta(lambda: nuvem.baixar_pasta(r2, velha.name, temporario / 'b2'),
                  'não confere com o manifesto')
confere(ok and not (temporario / 'b2' / velha.name).exists(),
        'arquivo trocado no R2: o download acusa e não entrega a pasta', msg)
ok, msg = levanta(lambda: nuvem.baixar_pasta(r2, '../etc', destino), 'inválido')
confere(ok, 'nome de pasta fora do formato recusado', msg)

print('=== 8. o script do backup e o vigia ===')
script = (ROOT / 'scripts/backup.sh').read_text(encoding='utf-8')
posicao_backup = script.find('-m ops.backup')
posicao_nuvem = script.find('-m ops.nuvem enviar')
confere(0 < posicao_backup < posicao_nuvem, 'backup.sh envia ao R2 depois do backup')
confere(re.search(r'-m ops\.nuvem enviar\s*\nCODIGO=\$\?', script) is not None
        and script.rstrip().endswith('fi'), 'backup.sh guarda o código do envio e sai com ele')
confere('flock' not in script[posicao_nuvem:], 'o envio roda fora da trava do deploy')
vigia = (ROOT / 'ops/vigiar_backup.py').read_text(encoding='utf-8')
confere('MARCA' in vigia and 'configurar(config)' in vigia,
        'o vigia cobra a marca quando a cópia está ligada')

servidor.shutdown()
shutil.rmtree(temporario)
print()
if failures:
    print(f'FALHAS ({len(failures)}):')
    for falha in failures:
        print(f'  - {falha}')
    raise SystemExit(1)
print('check_copia_nuvem: tudo certo')
