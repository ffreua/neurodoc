"""Arquivo morto: compactar o que já não muda, sem alterar um byte.

Prontuário é registro permanente e cresce sem parar. Um PDF de laudo com
imagem ocupa alguns megabytes; multiplicado por vinte anos de guarda legal,
o disco é o primeiro limite que uma clínica encontra.

A regra desta camada é uma só, e vale acima da economia de espaço: **o que
sai daqui tem de ser byte a byte o que entrou.** Documento médico assinado
tem a assinatura calculada sobre os bytes do arquivo; um byte diferente e a
assinatura deixa de conferir — o documento vira inválido sem que ninguém
perceba, até alguém tentar validá-lo anos depois.

Por isso o gzip, e não um formato com perdas ou uma reescrita do PDF: gzip
é reversível, e cada arquivo é conferido pelo SHA-256 **antes** de o
original ser apagado. Se a conferência falhar, o original fica onde está e
o arquivo comprimido é descartado.
"""

import gzip
import hashlib
import os
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import Attachment, AttachmentScanStatus
from .retention import BackupInProgress, backup_lock_active
from .storage import COMPRESSED_SUFFIX, is_compressed

#: Três meses, como pedido. É o prazo em que um documento deixa de ser
#: consultado com frequência: receita entregue, laudo lido, pedido de exame
#: realizado. Comprimir antes disso trocaria disco por processador no
#: material que ainda está sendo aberto todo dia.
COMPACT_AFTER_DAYS = 90

#: Nível 9. Isto roda uma vez por trimestre, fora do horário de
#: atendimento, sobre arquivo que ninguém está esperando — o tempo de
#: processador não é o recurso escasso aqui; o disco é.
COMPRESSION_LEVEL = 9

#: Abaixo disto não compensa: o cabeçalho do gzip mais o custo de
#: descomprimir a cada leitura superam o que se economiza.
MIN_SIZE_BYTES = 4096


class CompactionFailed(Exception):
    """A conferência não bateu. O original **não** foi tocado."""


def eligible(tenant_id=None, before=None):
    """Anexos publicados, antigos o bastante e ainda não comprimidos.

    Exclui o que está em quarentena ou recusado: aquilo não é arquivo
    definitivo, e o recusado nem tem arquivo. Exclui também o apagado
    logicamente — quem cuida dele é a coleta de lixo, que o remove em vez
    de comprimir.
    """
    cutoff = before or (timezone.now() - timezone.timedelta(days=COMPACT_AFTER_DAYS))
    queryset = Attachment.objects.filter(
        scan_status=AttachmentScanStatus.AVAILABLE,
        deleted_at__isnull=True,
        created_at__lt=cutoff,
        bytes__gte=MIN_SIZE_BYTES,
    ).exclude(storage_key='').exclude(storage_key__endswith=COMPRESSED_SUFFIX)
    if tenant_id is not None:
        queryset = queryset.filter(tenant_id=tenant_id)
    return queryset.order_by('created_at')


def _compress_file(source, destination):
    """Comprime e devolve o SHA-256 do que foi lido.

    Lê em blocos porque um laudo digitalizado passa de cem megabytes, e
    carregar isso inteiro na memória de um worker que processa uma fila
    inteira derruba o worker.
    """
    digest = hashlib.sha256()
    with open(source, 'rb') as entrada, gzip.open(
        destination, 'wb', compresslevel=COMPRESSION_LEVEL,
    ) as saida:
        while bloco := entrada.read(1024 * 1024):
            digest.update(bloco)
            saida.write(bloco)
    return digest.hexdigest()


def _verify(destination, expected_sha256):
    """Descomprime e confere. É o passo que autoriza apagar o original."""
    digest = hashlib.sha256()
    with gzip.open(destination, 'rb') as fh:
        while bloco := fh.read(1024 * 1024):
            digest.update(bloco)
    return digest.hexdigest() == expected_sha256


def compact_attachment(attachment, dry_run=False):
    """Comprime um anexo. Devolve (bytes_antes, bytes_depois) ou None.

    O mesmo arquivo em disco pode ser referenciado por mais de uma linha —
    a publicação deduplica por SHA-256 —, então todas as linhas que
    apontam para ele são atualizadas juntas. Atualizar só uma deixaria as
    outras apontando para um caminho que não existe mais.
    """
    if is_compressed(attachment) or not attachment.storage_key:
        return None
    source = Path(attachment.storage_key)
    if not source.is_file():
        return None

    original_size = source.stat().st_size
    if dry_run:
        return original_size, None

    destination = Path(f'{source}{COMPRESSED_SUFFIX}')
    temporario = Path(f'{destination}.incoming')
    try:
        digest = _compress_file(source, temporario)
        # O SHA-256 gravado na criação é a referência: se o arquivo em
        # disco já divergia dele, o problema é anterior à compactação e
        # apagar o original esconderia isso.
        if attachment.sha256 and digest != attachment.sha256:
            raise CompactionFailed(
                f'O arquivo em disco não confere com o SHA-256 registrado '
                f'({attachment.id}). Nada foi alterado.'
            )
        if not _verify(temporario, digest):
            raise CompactionFailed(
                f'O arquivo comprimido não devolveu os bytes originais '
                f'({attachment.id}). Nada foi alterado.'
            )
        os.replace(temporario, destination)
    except CompactionFailed:
        temporario.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporario.unlink(missing_ok=True)
        raise CompactionFailed(f'Falha de disco ao compactar {attachment.id}: {exc}') from exc

    compressed_size = destination.stat().st_size
    with transaction.atomic():
        Attachment.objects.filter(storage_key=str(source)).update(
            storage_key=str(destination),
        )
    # Só agora, com o banco já apontando para o comprimido: apagar antes
    # deixaria uma janela em que a linha aponta para um arquivo que não
    # existe mais e o download devolveria erro.
    source.unlink(missing_ok=True)
    return original_size, compressed_size


def compact(tenant_id=None, limit=None, dry_run=True):
    """Passa o arquivo morto. Devolve um resumo do que foi (ou seria) feito.

    Recusa-se a rodar durante backup, pelo mesmo motivo da coleta de lixo:
    mexer nos arquivos enquanto eles estão sendo copiados produz um backup
    com metade do material antigo e metade do novo.
    """
    if backup_lock_active():
        raise BackupInProgress('Backup em andamento; a compactação não roda agora.')

    resumo = {'considerados': 0, 'compactados': 0, 'antes': 0, 'depois': 0, 'falhas': []}
    queryset = eligible(tenant_id=tenant_id)
    if limit:
        queryset = queryset[:limit]

    for attachment in queryset:
        resumo['considerados'] += 1
        try:
            resultado = compact_attachment(attachment, dry_run=dry_run)
        except CompactionFailed as exc:
            resumo['falhas'].append(str(exc))
            record_audit_event(
                None, attachment.tenant_id, 'documents.compaction_failed',
                object_type='attachment', object_id=attachment.id, outcome='failure',
                integrity_metadata={'reason': str(exc)[:200]},
            )
            continue
        if resultado is None:
            continue
        antes, depois = resultado
        resumo['antes'] += antes
        if depois is not None:
            resumo['depois'] += depois
            resumo['compactados'] += 1

    if not dry_run and resumo['compactados']:
        record_audit_event(
            None, tenant_id, 'documents.archive_compacted',
            object_type='tenant', object_id=tenant_id, outcome='success',
            integrity_metadata={
                'files': resumo['compactados'],
                'bytes_before': resumo['antes'], 'bytes_after': resumo['depois'],
            },
        )
    return resumo
