"""Cópia dos backups cifrados no Cloudflare R2, fora do fornecedor da VPS.

Existe desde 2026-11-18. A VPS guarda os backups por 30 dias, mas eles
moram na própria VPS; o SSD externo depende de alguém plugá-lo (o NeuroDoc
ficou 40 dias sem cópia externa porque ele estava desconectado e ninguém
viu); e o servidor e os backups que ele guarda dependem de um fornecedor só
-- perder a conta levaria produção e backups juntos. O R2 é outra empresa,
e a cópia sai sozinha todo dia, logo depois do backup.

O que segura a cópia é a **trava do balde** (bucket lock), configurada na
Cloudflare: objeto gravado não pode ser apagado nem sobrescrito antes do
prazo, nem com a chave que esta VPS guarda. Quem invadir a VPS lê a chave e
consegue gravar coisa nova, não destruir o que já está lá. Os arquivos já
saem cifrados pelo `age` (`ops/backup.py`), e nem a VPS nem o R2 têm a
chave privada.

Biblioteca padrão, e não `boto3` nem `rclone`: o `boto3` traria dezenas de
pacotes para o `.venv-ops`, que a VPS monta à mão e que hoje só tem PyYAML;
o `rclone` seria um binário ou uma imagem nova a fixar e atualizar. A
assinatura SigV4 cabe em vinte linhas e é conferida contra o exemplo da
própria documentação da AWS em `checks/check_copia_nuvem.py`.

O corpo de cada envio é assinado com o SHA-256 **real** do arquivo
(`x-amz-content-sha256`), o mesmo do `manifest.json`: o R2 recusa o envio
se o que chegou não bate com o que saiu. Depois de cada envio, um `HEAD`
confere tamanho e hash de novo.

**Desligado enquanto `BACKUP_R2_*` estiverem vazios**, o padrão do
`.env.example`. O deploy completa o `.env` da VPS com o molde
(`ops/deploy.py::configuration`), e um padrão que ligasse a cópia sozinho
mudaria a produção no deploy seguinte.

Uso (na VPS, com o Python do `.venv-ops`):

    python -m ops.nuvem enviar            # o que o scripts/backup.sh chama
    python -m ops.nuvem listar            # backups completos no R2
    python -m ops.nuvem baixar PASTA DEST # baixa e confere com o manifesto
"""
import hashlib
import hmac
import http.client
import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

from ops.deploy import USER_AGENT, configuration

#: O mesmo formato de pasta que `ops/backup.py` cria e apaga.
PASTA = re.compile(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}')
#: Só o endpoint S3 do R2: conta (32 hex) e, opcional, a jurisdição. Aceitar
#: qualquer URL mandaria os backups para onde um `.env` errado apontasse.
ENDPOINT = re.compile(
    r'https://([0-9a-f]{32}(?:\.(?:eu|fedramp))?\.r2\.cloudflarestorage\.com)/?')
BALDE = re.compile(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]')
#: Arquivo que marca, dentro da pasta do backup, que ela está inteira no R2.
#: Fica junto da pasta para morrer com ela na retenção de `ops/backup.py`;
#: o restaurador só lê os arquivos listados no manifesto, e a cópia para o
#: SSD também, então a marca não atrapalha nenhum dos dois.
MARCA = 'NUVEM'
#: O R2 aceita até 5 GiB num envio simples. Acima disso precisaria do envio
#: em partes, que não existe aqui porque o maior arquivo, hoje, tem ~120 MB.
#: Falhar alto, com o motivo, é melhor que um erro do servidor sem contexto.
LIMITE_ENVIO = 4900 * 1024 * 1024
TENTATIVAS = 3
HASH_VAZIO = hashlib.sha256(b'').hexdigest()
#: O R2 assina com a região `auto`.
REGIAO = 'auto'
SEGURO = '-_.~'


class ErroNuvem(RuntimeError):
    pass


def consulta_canonica(consulta):
    return '&'.join(f'{quote(k, safe=SEGURO)}={quote(v, safe=SEGURO)}'
                    for k, v in sorted(consulta.items()))


def assinar(metodo, caminho, consulta, cabecalhos, hash_corpo, chave_id, segredo,
            regiao=REGIAO):
    """Devolve o `Authorization` AWS SigV4 de um pedido S3.

    `cabecalhos` são todos os que entram na assinatura, com nome em
    minúsculas, incluindo `host` e `x-amz-date`.
    """
    data_hora = cabecalhos['x-amz-date']
    dia = data_hora[:8]
    nomes = sorted(cabecalhos)
    canonicos = ''.join(f'{n}:{" ".join(str(cabecalhos[n]).split())}\n' for n in nomes)
    assinados = ';'.join(nomes)
    pedido = '\n'.join([metodo, caminho, consulta_canonica(consulta), canonicos,
                        assinados, hash_corpo])
    escopo = f'{dia}/{regiao}/s3/aws4_request'
    texto = '\n'.join(['AWS4-HMAC-SHA256', data_hora, escopo,
                       hashlib.sha256(pedido.encode()).hexdigest()])
    chave = ('AWS4' + segredo).encode()
    for parte in (dia, regiao, 's3', 'aws4_request'):
        chave = hmac.new(chave, parte.encode(), hashlib.sha256).digest()
    assinatura = hmac.new(chave, texto.encode(), hashlib.sha256).hexdigest()
    return (f'AWS4-HMAC-SHA256 Credential={chave_id}/{escopo}, '
            f'SignedHeaders={assinados}, Signature={assinatura}')


def codigo_de_erro(dados):
    """O `<Code>` do XML de erro do S3: diz o que houve sem repetir segredo."""
    achado = re.search(rb'<Code>([A-Za-z0-9]+)</Code>', dados or b'')
    return achado.group(1).decode() if achado else 'sem código'


def resumos(arquivo):
    """(sha256, md5) do arquivo, numa leitura só."""
    sha, md5 = hashlib.sha256(), hashlib.md5(usedforsecurity=False)
    with arquivo.open('rb') as origem:
        for bloco in iter(lambda: origem.read(1048576), b''):
            sha.update(bloco)
            md5.update(bloco)
    return sha.hexdigest(), md5.hexdigest()


def sha256_de(arquivo):
    return resumos(arquivo)[0]


class Nuvem:
    def __init__(self, host, balde, chave_id, segredo, conexao=None):
        self.host = host
        self.balde = balde
        self.chave_id = chave_id
        self.segredo = segredo
        # Trocável só para o roteiro, que fala com um servidor falso em HTTP.
        self.conexao = conexao or (lambda: http.client.HTTPSConnection(host, timeout=300))

    def _pedir(self, metodo, chave='', consulta=None, corpo=None, tamanho=0,
               hash_corpo=HASH_VAZIO, extras=None, saida=None):
        consulta = consulta or {}
        caminho = f'/{self.balde}' + (f'/{quote(chave, safe="/" + SEGURO)}' if chave else '')
        alvo = caminho + (f'?{consulta_canonica(consulta)}' if consulta else '')
        ultimo = None
        for tentativa in range(TENTATIVAS):
            if tentativa:
                time.sleep(5 * tentativa)
            # Data e assinatura refeitas a cada tentativa: o R2 recusa
            # assinatura com mais de 15 minutos.
            cabecalhos = {
                'host': self.host,
                'x-amz-date': datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                'x-amz-content-sha256': hash_corpo,
                **(extras or {}),
            }
            autorizacao = assinar(metodo, caminho, consulta, cabecalhos, hash_corpo,
                                  self.chave_id, self.segredo)
            conexao = self.conexao()
            try:
                conexao.putrequest(metodo, alvo, skip_host=True, skip_accept_encoding=True)
                for nome, valor in cabecalhos.items():
                    conexao.putheader(nome, valor)
                conexao.putheader('Authorization', autorizacao)
                conexao.putheader('User-Agent', USER_AGENT)
                if metodo == 'PUT':
                    conexao.putheader('Content-Length', str(tamanho))
                conexao.endheaders()
                if corpo is not None:
                    corpo.seek(0)
                    for bloco in iter(lambda: corpo.read(1048576), b''):
                        conexao.send(bloco)
                resposta = conexao.getresponse()
                if resposta.status == 200 and saida is not None:
                    saida.seek(0)
                    saida.truncate()
                    for bloco in iter(lambda: resposta.read(1048576), b''):
                        saida.write(bloco)
                    dados = b''
                else:
                    dados = resposta.read()
                if resposta.status >= 500:
                    raise ErroNuvem(f'o R2 devolveu {resposta.status}')
                return (resposta.status,
                        {k.lower(): v for k, v in resposta.getheaders()}, dados)
            except (OSError, http.client.HTTPException, ErroNuvem) as exc:
                ultimo = exc
            finally:
                conexao.close()
        raise ErroNuvem(f'{metodo} {chave or self.balde} falhou {TENTATIVAS} vezes: {ultimo}')

    def existente(self, chave):
        """(tamanho, sha256, md5) do objeto, ou None se ele não existe.

        O sha256 é o que este módulo gravou como metadado; o md5 é o `ETag`,
        que o R2 calcula sobre o que **guardou** num envio simples. É o MD5
        que prova o conteúdo do outro lado: o metadado só repete o que foi
        dito a ele.
        """
        status, cabecalhos, _ = self._pedir('HEAD', chave)
        if status == 404:
            return None
        if status != 200:
            raise ErroNuvem(f'HEAD {chave}: {status} (chave sem permissão de leitura no balde?)')
        return (int(cabecalhos.get('content-length', -1)),
                cabecalhos.get('x-amz-meta-sha256', ''),
                cabecalhos.get('etag', '').strip('"').lower())

    def enviar(self, chave, arquivo, sha, tamanho):
        with arquivo.open('rb') as corpo:
            status, _, dados = self._pedir('PUT', chave, corpo=corpo, tamanho=tamanho,
                                           hash_corpo=sha, extras={'x-amz-meta-sha256': sha})
        if status != 200:
            raise ErroNuvem(f'PUT {chave}: {status} {codigo_de_erro(dados)}')

    def baixar(self, chave, destino):
        with destino.open('xb') as saida:
            status, _, dados = self._pedir('GET', chave, saida=saida)
        if status != 200:
            destino.unlink()
            raise ErroNuvem(f'GET {chave}: {status} {codigo_de_erro(dados)}')

    def listar(self):
        """Todas as chaves do balde, com tamanho."""
        chaves, token = {}, None
        while True:
            consulta = {'list-type': '2'}
            if token:
                consulta['continuation-token'] = token
            status, _, dados = self._pedir('GET', consulta=consulta)
            if status != 200:
                raise ErroNuvem(f'listar: {status} {codigo_de_erro(dados)}')
            raiz = ElementTree.fromstring(dados)
            ns = raiz.tag[:raiz.tag.index('}') + 1] if raiz.tag.startswith('{') else ''
            for item in raiz.iter(f'{ns}Contents'):
                chaves[item.findtext(f'{ns}Key')] = int(item.findtext(f'{ns}Size') or 0)
            if raiz.findtext(f'{ns}IsTruncated') != 'true':
                return chaves
            token = raiz.findtext(f'{ns}NextContinuationToken')


def ler_credenciais(caminho):
    """Lê `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY` de um arquivo 600.

    Arquivo à parte, e não no `.env`: o `.env` é lido por mais coisas (o
    deploy, o `make_runtime`, quem faz `grep` nele para diagnosticar) e a
    chave não precisa estar em nenhuma delas.
    """
    if not caminho.is_absolute():
        raise ErroNuvem('BACKUP_R2_CREDENTIALS precisa ser um caminho absoluto')
    try:
        info = caminho.lstat()
    except FileNotFoundError:
        raise ErroNuvem(f'arquivo de credenciais do R2 não existe: {caminho}') from None
    if not stat.S_ISREG(info.st_mode):
        raise ErroNuvem(f'{caminho} precisa ser um arquivo comum, sem link')
    if hasattr(os, 'getuid') and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ErroNuvem(f'{caminho} precisa ser do usuário que roda o backup e ter '
                        f'modo 600 (chmod 600 {caminho})')
    valores = {}
    for linha in caminho.read_text(encoding='utf-8').splitlines():
        linha = linha.strip()
        if linha and not linha.startswith('#'):
            nome, _, valor = linha.partition('=')
            valores[nome.strip()] = valor.strip().strip('"\'')
    chave_id = valores.get('R2_ACCESS_KEY_ID', '')
    segredo = valores.get('R2_SECRET_ACCESS_KEY', '')
    # Confere o formato sem repetir o valor na mensagem: o erro vai para o
    # journal e para o e-mail de falha.
    if not re.fullmatch(r'[A-Za-z0-9]{16,128}', chave_id):
        raise ErroNuvem(f'R2_ACCESS_KEY_ID ausente ou mal colado em {caminho}')
    if not re.fullmatch(r'[A-Za-z0-9]{16,128}', segredo):
        raise ErroNuvem(f'R2_SECRET_ACCESS_KEY ausente ou mal colado em {caminho}')
    return chave_id, segredo


def configurar(config):
    """A `Nuvem` configurada no `.env`, ou None se a cópia está desligada."""
    endpoint, balde, credenciais = (
        (config.get(nome) or '').strip()
        for nome in ('BACKUP_R2_ENDPOINT', 'BACKUP_R2_BUCKET', 'BACKUP_R2_CREDENTIALS'))
    if not (endpoint or balde or credenciais):
        return None
    if not (endpoint and balde and credenciais):
        # Meio configurado é erro, e não "desligado": quem escreveu uma das
        # três quis ligar, e calar aqui seria um backup que não sai.
        raise ErroNuvem('BACKUP_R2_ENDPOINT, BACKUP_R2_BUCKET e BACKUP_R2_CREDENTIALS '
                        'vão juntos: preencha as três ou deixe as três vazias')
    achado = ENDPOINT.fullmatch(endpoint)
    if not achado:
        raise ErroNuvem('BACKUP_R2_ENDPOINT precisa ser '
                        'https://<id da conta>.r2.cloudflarestorage.com')
    if not BALDE.fullmatch(balde):
        raise ErroNuvem('BACKUP_R2_BUCKET inválido (minúsculas, números e hífen)')
    # O ProntDoc tem a regra espelhada (lá, contra o NeuroDoc). Um `.env`
    # copiado de uma instalação para a outra mandaria o prontuário de uma
    # empresa para o balde da outra, e a trava do balde o guardaria lá.
    if re.search(r'pront[-_ ]?doc', balde + endpoint, re.IGNORECASE):
        raise ErroNuvem('BACKUP_R2_BUCKET aponta para o ProntDoc; o NeuroDoc usa o '
                        'próprio balde. Nada foi enviado.')
    return Nuvem(achado.group(1), balde, *ler_credenciais(Path(credenciais)))


def pastas_pendentes(raiz):
    if not raiz.is_dir():
        return []
    return sorted(
        pasta for pasta in raiz.iterdir()
        if PASTA.fullmatch(pasta.name) and pasta.is_dir() and not pasta.is_symlink()
        and (pasta / 'COMPLETE').is_file() and not (pasta / MARCA).exists())


def enviar_pasta(nuvem, pasta):
    """Põe uma pasta de backup inteira no R2. Devolve quantos arquivos subiram agora."""
    manifesto = json.loads((pasta / 'manifest.json').read_text(encoding='utf-8'))
    # Dados primeiro, `COMPLETE` por último: no R2, como no disco, a pasta
    # só tem `COMPLETE` quando tudo o mais já chegou.
    nomes = sorted(manifesto['files']) + ['manifest.json', 'COMPLETE']
    enviados = 0
    for nome in nomes:
        arquivo = pasta / nome
        if arquivo.is_symlink() or not arquivo.is_file():
            raise ErroNuvem(f'{pasta.name}/{nome} sumiu ou não é arquivo comum')
        tamanho = arquivo.stat().st_size
        if tamanho > LIMITE_ENVIO:
            raise ErroNuvem(f'{pasta.name}/{nome} tem {tamanho} bytes, acima do envio '
                            'simples do R2: é hora de implementar o envio em partes')
        sha, md5 = resumos(arquivo)
        esperado = manifesto['files'].get(nome)
        if esperado and esperado['sha256'] != sha:
            raise ErroNuvem(f'{pasta.name}/{nome} não confere com o manifesto: o backup '
                            'local está corrompido, e uma cópia dele não serviria')
        chave = f'{pasta.name}/{nome}'
        remoto = nuvem.existente(chave)
        if remoto == (tamanho, sha, md5):
            continue  # subiu numa tentativa anterior que caiu no meio
        if remoto is not None:
            raise ErroNuvem(f'{chave} já existe no R2 com outro conteúdo, e a trava do '
                            'balde impede sobrescrever. Investigue antes de qualquer coisa.')
        nuvem.enviar(chave, arquivo, sha, tamanho)
        if nuvem.existente(chave) != (tamanho, sha, md5):
            raise ErroNuvem(f'{chave}: o R2 aceitou o envio, mas o tamanho ou o hash '
                            'que ele devolve não confere')
        enviados += 1
    # Escrever a marca muda a data da pasta, e é por essa data que
    # `ops/backup.py` apaga o que passou da retenção: sem devolver a data
    # original, a primeira cópia de um mês de backups antigos esticaria a
    # retenção de todos eles por mais um mês e encheria o disco.
    original = pasta.stat()
    (pasta / MARCA).write_text(datetime.now(timezone.utc).isoformat() + '\n')
    os.utime(pasta, ns=(original.st_atime_ns, original.st_mtime_ns))
    return enviados


def baixar_pasta(nuvem, pasta, destino):
    """Baixa um backup do R2 e confere cada arquivo com o manifesto."""
    if not PASTA.fullmatch(pasta):
        raise ErroNuvem(f'nome de pasta inválido: {pasta}')
    final = destino / pasta
    parcial = destino / f'{pasta}.parcial'
    if final.exists() or parcial.exists():
        raise ErroNuvem(f'{final} (ou {parcial.name}) já existe; não sobrescrevo')
    parcial.mkdir(mode=0o700, parents=True)
    nuvem.baixar(f'{pasta}/manifest.json', parcial / 'manifest.json')
    manifesto = json.loads((parcial / 'manifest.json').read_text(encoding='utf-8'))
    for nome, info in sorted(manifesto['files'].items()):
        if '/' in nome or nome.startswith('.'):
            raise ErroNuvem(f'nome de arquivo inesperado no manifesto: {nome!r}')
        arquivo = parcial / nome
        nuvem.baixar(f'{pasta}/{nome}', arquivo)
        if arquivo.stat().st_size != info['bytes'] or sha256_de(arquivo) != info['sha256']:
            raise ErroNuvem(f'{pasta}/{nome} baixou, mas não confere com o manifesto')
    nuvem.baixar(f'{pasta}/COMPLETE', parcial / 'COMPLETE')
    parcial.rename(final)
    return final


USO = ('uso: python -m ops.nuvem enviar | listar | baixar PASTA DESTINO')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    comando = argv[0] if argv else ''
    if comando not in ('enviar', 'listar', 'baixar') or (comando == 'baixar') != (len(argv) == 3):
        print(USO, file=sys.stderr)
        return 2
    try:
        config = configuration()
        nuvem = configurar(config)
        if nuvem is None:
            print('Cópia no R2 desligada (BACKUP_R2_* vazios no .env).')
            return 0 if comando == 'enviar' else 1
        if comando == 'enviar':
            pendentes = pastas_pendentes(Path(config['BACKUP_DIR']))
            falhas = []
            for pasta in pendentes:
                try:
                    enviados = enviar_pasta(nuvem, pasta)
                    print(f'{pasta.name}: inteiro no R2 ({enviados} arquivo(s) enviado(s) agora).')
                except ErroNuvem as exc:
                    falhas.append(pasta.name)
                    print(f'FALHOU {pasta.name}: {exc}', file=sys.stderr)
            if not pendentes:
                print('Nada pendente: os backups completos já estão no R2.')
            if falhas:
                print(f'{len(falhas)} backup(s) sem cópia no R2; a próxima execução tenta '
                      'de novo.', file=sys.stderr)
                return 1
            return 0
        if comando == 'listar':
            chaves = nuvem.listar()
            pastas = sorted({c.split('/', 1)[0] for c in chaves if c.endswith('/COMPLETE')})
            for pasta in pastas:
                total = sum(t for c, t in chaves.items() if c.startswith(pasta + '/'))
                print(f'{pasta}  {total / 1048576:.1f} MiB')
            print(f'{len(pastas)} backup(s) completo(s) no R2; '
                  f'{sum(chaves.values()) / 1073741824:.2f} GiB no balde.')
            return 0
        final = baixar_pasta(nuvem, argv[1], Path(argv[2]).resolve())
        print(f'Baixado e conferido com o manifesto: {final}')
        return 0
    except ErroNuvem as exc:
        print(f'ERRO: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
