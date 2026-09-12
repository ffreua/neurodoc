"""Fotografia do paciente: validar, guardar, ler e apagar.

Fica ao lado de `tenancy.branding`, e não dentro de `documents.storage`,
pela mesma razão que o logotipo da clínica: anexo passa por quarentena,
antivírus e cota do inquilino porque chega de fora — do paciente, de um
exame externo, de um laboratório. A fotografia é **uma por paciente**,
enviada por quem faz o cadastro, e substituir a anterior é o
comportamento certo. Pelo fluxo de anexo, cada troca de foto viraria um
anexo novo no prontuário, e a ficha acumularia um histórico de retratos
que ninguém pediu.

Há uma diferença honesta em relação ao logotipo, e ela justifica repetir
as defesas em vez de afrouxá-las: o logotipo vem de quem administra a
clínica, e esta foto pode ter vindo do celular de um familiar. Por isso o
tipo é conferido pelos **bytes** e não pela extensão nem pelo que o
navegador declarou, e por isso quem serve o arquivo manda
`Content-Security-Policy` e `nosniff` junto.

Sobre consentimento: o registro é feito em papel, fora do sistema
(decisão do produto, setembro/2026). O que fica aqui é a trilha de
auditoria — quem enviou e quando —, e um aviso na tela para que a
autorização assinada não seja esquecida no balcão.
"""

import base64
import binascii
import os
import re
from pathlib import Path

import magic
from django.conf import settings
from django.utils import timezone

#: 2 MB. Uma foto de identificação não precisa de mais, e o limite existe
#: para que um envio errado — o PDF de um exame, um vídeo — pare aqui em
#: vez de ocupar o volume de mídia da clínica.
MAX_PHOTO_BYTES = 2 * 1024 * 1024

#: SVG está fora, como no logotipo: é XML, executa script servido inline, e
#: nitidez em qualquer tamanho não é o que se pede de um retrato.
ALLOWED_PHOTO_MIMES = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/webp': '.webp',
}

#: `data:image/jpeg;base64,...` — o que a captura pela câmera envia. O
#: `charset` é aceito porque alguns navegadores o inserem; o que vale é o
#: que `magic` disser dos bytes decodificados, nunca este rótulo.
DATA_URL = re.compile(r'^data:image/[a-z+.-]+(;[a-z0-9-]+=[^;,]+)*;base64,(?P<payload>.+)$', re.IGNORECASE | re.DOTALL)


class PhotoRejected(Exception):
    pass


def _photo_dir(tenant_id, patient_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'patients' / str(patient_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def decode_capture(value):
    """Bytes de uma captura da câmera, ou None quando não houve captura.

    O campo chega vazio na maioria dos envios — quem mandou arquivo não
    usou a câmera —, e isso não é erro. O que é erro é vir preenchido com
    algo que não decodifica: aí a pessoa capturou, viu a prévia na tela e
    o cadastro seria salvo sem foto nenhuma, em silêncio.
    """
    value = (value or '').strip()
    if not value:
        return None
    match = DATA_URL.match(value)
    if match is None:
        raise PhotoRejected('A captura da câmera não chegou em formato reconhecível. Tente de novo ou envie um arquivo.')
    try:
        # `validate=True`: sem isso o base64 do Python descarta em silêncio
        # qualquer caractere fora do alfabeto e devolve bytes truncados, que
        # depois falhariam em `magic` com uma mensagem sobre formato de
        # imagem — longe da causa, que é a transmissão.
        return base64.b64decode(match.group('payload'), validate=True)
    except (binascii.Error, ValueError):
        raise PhotoRejected('A captura da câmera chegou corrompida. Tente de novo ou envie um arquivo.')


def validate_photo(content):
    """Confere tamanho e formato pelos bytes. Devolve (mime, extensão)."""
    if not content:
        raise PhotoRejected('Arquivo vazio.')
    if len(content) > MAX_PHOTO_BYTES:
        limit = MAX_PHOTO_BYTES // (1024 * 1024)
        raise PhotoRejected(f'A imagem passa de {limit} MB. Envie uma versão menor.')
    mime = magic.from_buffer(content, mime=True)
    if mime not in ALLOWED_PHOTO_MIMES:
        raise PhotoRejected(
            'Formato não aceito. Envie PNG, JPEG ou WebP — '
            f'o arquivo enviado é {mime}.'
        )
    return mime, ALLOWED_PHOTO_MIMES[mime]


def store_photo(patient, content):
    """Grava a fotografia e aponta o paciente para ela.

    Grava num arquivo temporário e renomeia por cima do destino:
    `os.replace` é atômico dentro do mesmo sistema de arquivos, e sem isso
    um envio interrompido deixaria meia imagem no lugar do retrato que
    funcionava — e a ficha passaria a mostrar um arquivo truncado.

    O anterior é removido **depois** de o novo estar no lugar, e só quando
    muda de extensão: trocar um JPEG por outro JPEG já sobrescreveu.

    Não salva o paciente. Quem chama decide se isto entra na mesma
    transação do cadastro (ao criar) ou numa gravação própria de um campo
    só (ao trocar a foto de quem já existe) — e trocar a foto não deve
    incrementar `row_version`, que é o que sinaliza edição concorrente do
    cadastro.
    """
    mime, extension = validate_photo(content)
    previous = patient.photo_path
    destination = _photo_dir(patient.tenant_id, patient.id) / f'photo{extension}'
    staging = destination.with_suffix(destination.suffix + '.incoming')
    staging.write_bytes(content)
    os.replace(staging, destination)

    patient.photo_path = str(destination)
    patient.photo_mime = mime
    patient.photo_bytes = len(content)
    patient.photo_updated_at = timezone.now()

    if previous and previous != str(destination):
        Path(previous).unlink(missing_ok=True)
    return patient


def discard_photo(patient):
    """Remove a fotografia. O cadastro e a história do paciente ficam."""
    if patient.photo_path:
        Path(patient.photo_path).unlink(missing_ok=True)
    patient.photo_path = ''
    patient.photo_mime = ''
    patient.photo_bytes = 0
    patient.photo_updated_at = None
    return patient


#: Os campos que `store_photo` e `discard_photo` mexem. Existe para o
#: `update_fields` da gravação da foto não precisar repeti-los em cada
#: chamador — e para que acrescentar um campo aqui não deixe um chamador
#: gravando só metade do estado.
PHOTO_FIELDS = ['photo_path', 'photo_mime', 'photo_bytes', 'photo_updated_at']


def read_photo(patient):
    """Bytes da fotografia, ou None quando não há (ou o arquivo sumiu).

    Devolver None em vez de estourar é deliberado: o arquivo pode ter ido
    embora numa restauração de backup parcial, e uma ficha de paciente que
    responde 500 por causa de um retrato ausente é pior do que uma ficha
    que mostra a inicial do nome.
    """
    if not patient or not patient.photo_path:
        return None
    path = Path(patient.photo_path)
    if not path.is_file():
        return None
    return path.read_bytes()
