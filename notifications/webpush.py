"""O protocolo do Web Push, sem biblioteca de terceiros.

Três RFCs, e só o pedaço delas que um servidor precisa:

- **RFC 8291** (cifra da mensagem): o corpo vai cifrado para o aparelho, e
  o serviço de push do Google, da Apple ou da Mozilla, que o transporta,
  não o lê;
- **RFC 8188** (`aes128gcm`): o formato do corpo cifrado, um registro só;
- **RFC 8292** (VAPID): a assinatura que prova ao serviço de push que o
  aviso vem do mesmo servidor que pediu a inscrição.

**Por que não `pywebpush`.** As versões novas dela puxam `aiohttp`,
`http-ece` e `py-vapid` para fazer o que `cryptography` e `httpx` — que já
estão no lock, com hash — fazem em poucas linhas. Cada dependência nova é
um pacote a mais com permissão de rodar no worker que guarda as chaves de
SMS, de e-mail e de IA. O risco de escrever a cifra à mão é errar um byte;
o roteiro `check_push` confere a cifra contra o exemplo do Apêndice A da
RFC 8291, byte a byte, e a assinatura VAPID contra a chave pública.

Nada aqui conhece Django, usuário ou clínica: entra chave e texto, sai o
pedido HTTP. A regra do produto mora em `notifications.push`.
"""

import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

#: Tamanho do registro declarado no cabeçalho. O corpo inteiro cabe num
#: registro só (o aviso tem poucas centenas de bytes); 4096 é o valor que
#: todos os serviços aceitam.
TAMANHO_DO_REGISTRO = 4096

#: O teto do serviço de push para o corpo cifrado. O aviso do produto nunca
#: chega perto, e passar daqui é defeito nosso, não do serviço.
CORPO_MAXIMO = 4000


def b64url(dados):
    return base64.urlsafe_b64encode(dados).rstrip(b'=').decode('ascii')


def de_b64url(texto):
    texto = texto.strip()
    return base64.urlsafe_b64decode(texto + '=' * (-len(texto) % 4))


# ------------------------------------------------------------------ chaves

def gerar_chaves():
    """Um par P-256 novo: `(privada_b64url, publica_b64url)`.

    A privada vai como os 32 bytes do escalar, e a pública como o ponto não
    comprimido de 65 bytes — o formato que o navegador quer em
    `applicationServerKey`.
    """
    privada = ec.generate_private_key(ec.SECP256R1())
    return _privada_em_texto(privada), publica_da_privada(_privada_em_texto(privada))


def _privada_em_texto(privada):
    return b64url(privada.private_numbers().private_value.to_bytes(32, 'big'))


def _carregar_privada(texto):
    return ec.derive_private_key(int.from_bytes(de_b64url(texto), 'big'), ec.SECP256R1())


def _ponto(publica):
    return publica.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )


def publica_da_privada(privada_texto):
    return b64url(_ponto(_carregar_privada(privada_texto).public_key()))


def chave_do_aparelho_valida(p256dh, auth):
    """A chave pública e o segredo que o navegador entregou fazem sentido?

    Conferido na inscrição, e não só no envio: uma linha com chave torta
    ficaria no banco falhando em todo aviso, e o erro apareceria longe de
    quem o causou.
    """
    try:
        ponto = de_b64url(p256dh)
        segredo = de_b64url(auth)
        if len(ponto) != 65 or len(segredo) != 16:
            return False
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ponto)
    except (ValueError, TypeError):
        return False
    return True


# ------------------------------------------------------------------ cifra

def _hkdf(salt, ikm, info, tamanho):
    return HKDF(algorithm=hashes.SHA256(), length=tamanho, salt=salt, info=info).derive(ikm)


def cifrar(mensagem, p256dh, auth, *, _privada_do_servidor=None, _salt=None):
    """O corpo `aes128gcm` da RFC 8291 para este aparelho.

    `_privada_do_servidor` e `_salt` existem só para o roteiro reproduzir o
    exemplo da RFC; em uso normal os dois são novos a cada aviso — repetir o
    sal com a mesma chave quebraria a cifra.
    """
    publica_do_aparelho = de_b64url(p256dh)
    segredo = de_b64url(auth)
    privada = (_carregar_privada(_privada_do_servidor) if _privada_do_servidor
               else ec.generate_private_key(ec.SECP256R1()))
    publica_do_servidor = _ponto(privada.public_key())
    salt = _salt if _salt is not None else os.urandom(16)

    compartilhado = privada.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), publica_do_aparelho),
    )
    info = b'WebPush: info\x00' + publica_do_aparelho + publica_do_servidor
    ikm = _hkdf(segredo, compartilhado, info, 32)
    chave = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)

    # `\x02` é o delimitador do último (e único) registro, sem preenchimento.
    cifrado = AESGCM(chave).encrypt(nonce, mensagem + b'\x02', None)
    cabecalho = (salt + struct.pack('!L', TAMANHO_DO_REGISTRO)
                 + bytes([len(publica_do_servidor)]) + publica_do_servidor)
    return cabecalho + cifrado


# ------------------------------------------------------------------ VAPID

def assinatura_vapid(endpoint, privada_texto, assunto, *, agora=None):
    """O cabeçalho `Authorization` da RFC 8292 para este serviço de push.

    `aud` é a origem do endpoint (o serviço confere que a assinatura foi
    feita para ele), e o prazo é de 12 horas: o teto que a Apple aceita é
    24, e o aviso é assinado na hora de sair.
    """
    partes = urlsplit(endpoint)
    agora = int(agora if agora is not None else time.time())
    cabecalho = b64url(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    corpo = b64url(json.dumps({
        'aud': f'{partes.scheme}://{partes.netloc}',
        'exp': agora + 12 * 3600,
        'sub': assunto,
    }, separators=(',', ':')).encode())
    assinado = f'{cabecalho}.{corpo}'.encode('ascii')
    privada = _carregar_privada(privada_texto)
    r, s = decode_dss_signature(privada.sign(assinado, ec.ECDSA(hashes.SHA256())))
    # JWT quer `r || s` cru, 32 bytes cada; `cryptography` devolve DER.
    token = f'{cabecalho}.{corpo}.{b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}'
    return f'vapid t={token}, k={publica_da_privada(privada_texto)}'


def montar_pedido(endpoint, p256dh, auth, mensagem, privada_texto, assunto, *,
                  ttl=86400, urgencia='normal', topico=''):
    """Cabeçalhos e corpo do `POST` ao serviço de push."""
    corpo = cifrar(mensagem, p256dh, auth)
    if len(corpo) > CORPO_MAXIMO:
        raise ValueError('aviso grande demais para o serviço de push')
    cabecalhos = {
        'Authorization': assinatura_vapid(endpoint, privada_texto, assunto),
        'Content-Encoding': 'aes128gcm',
        'Content-Type': 'application/octet-stream',
        'TTL': str(int(ttl)),
        'Urgency': urgencia,
    }
    if topico:
        # `Topic` faz o serviço trocar um aviso ainda não entregue pelo
        # novo do mesmo assunto, em vez de entregar os dois quando o
        # aparelho voltar à rede. Até 32 caracteres do alfabeto base64url.
        cabecalhos['Topic'] = topico[:32]
    return cabecalhos, corpo
