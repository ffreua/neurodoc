from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import Attachment, AttachmentScanStatus

BACKUP_LOCK_PATH = Path('/data/media/.backup_lock')
GC_MIN_AGE_DAYS = 30

#: Guarda mínima do prontuário, em anos, contados **do último registro**.
#:
#: Não é escolha de produto e não é configurável. A **Lei 13.787/2018,
#: art. 6º** permite eliminar prontuário — em papel ou digitalizado —
#: apenas decorridos 20 anos do último registro; a **Resolução CFM
#: 1.821/2007** manda guarda permanente para o que está arquivado
#: eletronicamente.
#:
#: A LGPD não encurta esse prazo: o art. 16, I dela abre exceção expressa
#: para "cumprimento de obrigação legal ou regulatória", que é o caso.
#: Eliminar antes disso é destruição de prova, não economia de disco.
RETENTION_YEARS = 20

#: Do **último** registro, e não da data de cada documento. Um paciente
#: atendido em 2010 e de novo em 2024 tem o prontuário inteiro protegido
#: até 2044 — a lei fala do prontuário, não de cada peça dele.
RETENTION_DAYS = RETENTION_YEARS * 365


class BackupInProgress(Exception):
    pass


def backup_lock_active():
    return BACKUP_LOCK_PATH.exists()


@transaction.atomic
def soft_delete_attachment(attachment, actor_id, reason):
    """Logical removal only — the file stays on disk until the GC pass
    considers it eligible; a deleted row is simply excluded from listings
    and downloads.
    """
    attachment.deleted_at = timezone.now()
    attachment.deleted_reason = reason[:255]
    attachment.save(update_fields=['deleted_at', 'deleted_reason'])
    record_audit_event(
        actor_id, attachment.tenant_id, 'documents.attachment_soft_deleted',
        object_type='attachment', object_id=attachment.id, outcome='success',
    )
    return attachment


def garbage_collect(dry_run=True):
    """Physically deletes the on-disk file for attachments soft-deleted long
    enough ago, skipping entirely while a backup is in progress and never
    touching a file another Attachment row still references by storage_key.
    """
    if backup_lock_active():
        raise BackupInProgress('Backup lock present; GC refuses to run')

    cutoff = timezone.now() - timezone.timedelta(days=GC_MIN_AGE_DAYS)
    candidates = Attachment.objects.filter(
        deleted_at__isnull=False, deleted_at__lt=cutoff,
    ).exclude(scan_status=AttachmentScanStatus.REJECTED)

    removed = []
    for attachment in candidates:
        if not attachment.storage_key:
            continue
        still_referenced = Attachment.objects.filter(
            storage_key=attachment.storage_key, deleted_at__isnull=True,
        ).exclude(id=attachment.id).exists()
        if still_referenced:
            continue
        removed.append(attachment.id)
        if not dry_run:
            Path(attachment.storage_key).unlink(missing_ok=True)
            attachment.storage_key = ''
            attachment.save(update_fields=['storage_key'])
    return removed


# --------------------------------------------------------------------------
# Guarda legal do prontuário
# --------------------------------------------------------------------------

def last_record_at(patient):
    """A data do registro mais recente daquele paciente.

    É o marco de onde os 20 anos contam. Olha tudo o que constitui
    prontuário — atendimento, documento emitido, anexo e medição —, e não
    só o mais óbvio: um paciente cujo último atendimento foi em 2010 mas
    que teve um exame anexado em 2024 está com o prontuário em uso, e
    contar do atendimento o eliminaria catorze anos cedo.

    Devolve `None` quando não há registro nenhum. Cadastro sem prontuário
    não é prontuário, e a regra de guarda não se aplica a ele.
    """
    from clinical.models import Encounter

    from .models import Attachment, MedicalDocument

    candidatos = [
        Encounter.objects.filter(patient=patient).order_by('-occurred_at')
        .values_list('occurred_at', flat=True).first(),
        MedicalDocument.objects.filter(patient=patient).order_by('-created_at')
        .values_list('created_at', flat=True).first(),
        Attachment.objects.filter(patient=patient).order_by('-created_at')
        .values_list('created_at', flat=True).first(),
        patient.observations.order_by('-observed_at')
        .values_list('observed_at', flat=True).first(),
    ]
    datas = [d for d in candidatos if d is not None]
    return max(datas) if datas else None


def retention_expires_at(patient):
    """Quando este prontuário passa a poder ser eliminado, ou `None`."""
    ultimo = last_record_at(patient)
    if ultimo is None:
        return None
    return ultimo + timezone.timedelta(days=RETENTION_DAYS)


def retention_report(tenant_id=None):
    """Situação de guarda de cada prontuário, para quem administra.

    Serve à pergunta que aparece na auditoria e no pedido de exclusão de
    um paciente: "há quanto tempo este prontuário está parado, e quando ele
    poderia ser eliminado?". Nunca elimina nada.
    """
    from patients.models import Patient

    agora = timezone.now()
    pacientes = Patient.objects.all()
    if tenant_id is not None:
        pacientes = pacientes.filter(tenant_id=tenant_id)

    linhas = []
    for patient in pacientes.select_related('tenant').iterator():
        expira = retention_expires_at(patient)
        linhas.append({
            'patient': patient,
            'last_record_at': last_record_at(patient),
            'expires_at': expira,
            'eligible': expira is not None and expira <= agora,
            'years_left': None if expira is None else round((expira - agora).days / 365, 1),
        })
    return linhas


def purge_candidates(tenant_id=None):
    """Prontuários cujo prazo legal de guarda já venceu.

    Na prática esta lista fica vazia por vinte anos, e é assim que tem de
    ser. Ela existe para que, quando deixar de ficar, a eliminação seja uma
    decisão consciente com uma lista na frente — e não um `DELETE` que
    alguém escreve no console com pressa.
    """
    return [linha for linha in retention_report(tenant_id) if linha['eligible']]
