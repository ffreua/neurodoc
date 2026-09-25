from celery import shared_task

from integrations.antivirus import DefinitionUpdateFailed, ScanInfected, ScanUnavailable, scan_file, update_definitions

from .models import Attachment, AttachmentScanStatus
from .storage import publish_from_quarantine, reject_and_discard


@shared_task(name='documents.tasks.scan_attachment', expires=600)
def scan_attachment(attachment_id):
    attachment = Attachment.objects.filter(id=attachment_id, scan_status=AttachmentScanStatus.QUARANTINED).first()
    if attachment is None:
        return {'skipped': True}
    try:
        scan_file(attachment.storage_key)
    except ScanInfected as exc:
        reject_and_discard(attachment, f'Malware detected: {exc.signature}')
        return {'status': 'rejected', 'signature': exc.signature}
    except ScanUnavailable as exc:
        attachment.scan_error = str(exc)[:255]
        attachment.save(update_fields=['scan_error'])
        return {'status': 'quarantined', 'error': str(exc)}
    publish_from_quarantine(attachment)
    return {'status': 'available'}


@shared_task(name='documents.tasks.update_clamav_definitions', expires=3600)
def update_clamav_definitions():
    """Runs every 6h from Celery beat (see CELERY_BEAT_SCHEDULE); a failure
    here just leaves the existing definitions in place — scan_attachment
    keeps failing closed (ScanUnavailable) if they go stale enough that
    clamscan itself refuses them.
    """
    try:
        update_definitions()
    except DefinitionUpdateFailed as exc:
        return {'status': 'failed', 'error': str(exc)}
    return {'status': 'updated'}


@shared_task(name='documents.tasks.compact_archive', expires=6 * 60 * 60)
def compact_archive_task():
    """Compactação trimestral do arquivo morto.

    Agendada pelo `crontab` do beat para a madrugada do primeiro dia de
    cada trimestre: é trabalho de disco pesado e não deve disputar E/S com
    o atendimento. Nada é apagado sem o SHA-256 conferir — ver
    `documents.archive`.

    Falha em silêncio quando há backup em andamento, e tenta de novo no
    trimestre seguinte: adiar a compactação por três meses custa disco;
    mexer nos arquivos durante a cópia custa o backup.
    """
    from .archive import compact
    from .retention import BackupInProgress

    try:
        return compact(dry_run=False)
    except BackupInProgress as exc:
        return {'skipped': True, 'reason': str(exc)}


@shared_task(name='documents.tasks.garbage_collect', expires=6 * 60 * 60)
def garbage_collect_task():
    """Coleta semanal do arquivo de anexo ja apagado pelo usuario.

    A funcao existia pronta e **nao era chamada por ninguem** em producao --
    so por `checks/check_backup.py`. A consequencia tinha dois lados: o
    arquivo de um anexo que o usuario mandou remover ficava legivel em disco
    para sempre (o que e problema de privacidade, nao de espaco), e o disco
    so crescia.

    **Comeca em ensaio.** `DOCUMENTS_GC_DRY_RUN` nasce `True`: a passagem
    percorre tudo, registra na trilha quantos arquivos removeria e quantos a
    guarda legal reteve, e **nao apaga nada**. Virar para `False` e uma
    mudanca de `.env`, nao um deploy -- de proposito, porque a decisao de
    autorizar apagamento permanente de arquivo clinico e do controlador e
    nao cabe num commit.

    A ordem recomendada, e o motivo dela: esta funcao nunca executou em
    producao. A logica de retencao e verificada contra o banco de
    demonstracao, nao contra a mistura real de vinte anos de uma clinica. Um
    mes de "teria removido N, reteve M" converte um salto num degrau. E so
    se liga o apagamento depois de a **restauracao do backup ter sido
    testada num host separado**: apagar arquivo so e seguro quando se provou
    que se sabe traze-lo de volta.

    O que ela toca, mesmo com `dry_run=False`: apenas anexo que o usuario ja
    apagou, passados `GC_MIN_AGE_DAYS` (30) dias, liberado pela guarda de 20
    anos da Lei 13.787/2018, e que nenhum outro anexo vivo referencie. Ela
    nao apaga nada que ninguem mandou apagar -- termina uma exclusao que o
    usuario pediu.

    Falha em silencio quando ha backup em andamento, como a compactacao, e
    pelo mesmo motivo: mexer nos arquivos durante a copia custa o backup.
    """
    from django.conf import settings

    from .retention import BackupInProgress, garbage_collect

    ensaio = getattr(settings, 'DOCUMENTS_GC_DRY_RUN', True)
    try:
        removidos, retidos = garbage_collect(dry_run=ensaio)
    except BackupInProgress as exc:
        return {'skipped': True, 'reason': str(exc)}
    return {
        'dry_run': ensaio,
        'removed': len(removidos),
        'held_by_retention': len(retidos),
    }
