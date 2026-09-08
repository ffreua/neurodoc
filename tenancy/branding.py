"""Logotipo da clínica: validar, guardar e apagar.

Fica separado de `documents.storage` porque não é anexo de paciente. Anexo
passa por quarentena, antivírus e cota do inquilino, e é assim que tem de
ser: chega de fora, do paciente ou de um exame externo. O logotipo é
enviado por quem administra a clínica, é um arquivo por organização, e
substituir o anterior é o comportamento certo. Passá-lo pelo fluxo de
anexo criaria um registro de anexo por troca de logotipo, na ficha de
paciente nenhum.

O que ele compartilha com o anexo é a desconfiança quanto ao conteúdo: o
tipo é conferido pelos bytes (`magic`), não pela extensão nem pelo que o
navegador declarou.
"""

import os
from pathlib import Path

import magic
from django.conf import settings
from django.utils import timezone

#: 2 MB. Um logotipo de cabeçalho não precisa de mais, e o limite existe
#: para que um envio errado — a foto de uma fachada, um PDF renomeado —
#: pare aqui em vez de virar um PDF de receita de 40 MB.
MAX_LOGO_BYTES = 2 * 1024 * 1024

#: SVG está fora de propósito. É XML, executa script quando servido inline,
#: e o ganho — nitidez em qualquer tamanho — não paga o risco de servir
#: markup de origem externa a partir do domínio da clínica. PNG com fundo
#: transparente resolve o mesmo problema de cabeçalho.
ALLOWED_LOGO_MIMES = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/webp': '.webp',
}


class LogoRejected(Exception):
    pass


def _branding_dir(tenant_id):
    path = Path(settings.MEDIA_ROOT) / str(tenant_id) / 'branding'
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_logo(content):
    """Confere tamanho e formato pelos bytes. Devolve (mime, extensão)."""
    if not content:
        raise LogoRejected('Arquivo vazio.')
    if len(content) > MAX_LOGO_BYTES:
        limit = MAX_LOGO_BYTES // (1024 * 1024)
        raise LogoRejected(f'A imagem passa de {limit} MB. Envie uma versão menor.')
    mime = magic.from_buffer(content, mime=True)
    if mime not in ALLOWED_LOGO_MIMES:
        raise LogoRejected(
            'Formato não aceito. Envie PNG, JPEG ou WebP — '
            f'o arquivo enviado é {mime}.'
        )
    return mime, ALLOWED_LOGO_MIMES[mime]


def store_logo(profile, content):
    """Grava o logotipo e aponta o perfil para ele.

    A gravação é feita em arquivo temporário e renomeada por cima do
    destino: `os.replace` é atômico dentro do mesmo sistema de arquivos, e
    sem isso um envio interrompido deixaria meio arquivo no lugar do
    logotipo que funcionava. O documento que estivesse sendo gerado naquele
    instante sairia com a imagem truncada.

    O arquivo antigo é removido **depois** de o novo estar no lugar, e só
    quando muda de extensão — trocar um PNG por outro PNG já sobrescreveu.
    """
    mime, extension = validate_logo(content)
    previous = profile.logo_path
    destination = _branding_dir(profile.tenant_id) / f'logo{extension}'
    staging = destination.with_suffix(destination.suffix + '.incoming')
    staging.write_bytes(content)
    os.replace(staging, destination)

    profile.logo_path = str(destination)
    profile.logo_mime = mime
    profile.logo_bytes = len(content)
    profile.logo_updated_at = timezone.now()

    if previous and previous != str(destination):
        Path(previous).unlink(missing_ok=True)
    return profile


def discard_logo(profile):
    """Remove o logotipo. Os documentos já emitidos não mudam.

    Um PDF assinado é um arquivo pronto no disco: o logotipo que ele traz
    foi desenhado dentro dele na emissão. Apagar aqui muda o que os
    **próximos** documentos vão mostrar, e é isso que se quer — documento
    emitido não se reescreve.
    """
    if profile.logo_path:
        Path(profile.logo_path).unlink(missing_ok=True)
    profile.logo_path = ''
    profile.logo_mime = ''
    profile.logo_bytes = 0
    profile.logo_updated_at = None
    return profile


def read_logo(profile):
    """Bytes do logotipo, ou None quando não há (ou o arquivo sumiu).

    Devolver None em vez de estourar é deliberado: o arquivo pode ter ido
    embora numa restauração de backup parcial, e isso não pode impedir a
    emissão de uma receita. O documento sai sem logotipo.
    """
    if not profile or not profile.logo_path:
        return None
    path = Path(profile.logo_path)
    if not path.is_file():
        return None
    return path.read_bytes()
