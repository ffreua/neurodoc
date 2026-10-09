from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event
from ops.locks import BACKUP_LOCK

from .models import Attachment, AttachmentClassification, AttachmentScanStatus

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


class BackupInProgress(Exception):
    pass


@contextmanager
def backup_exclusive(operacao):
    """Segura a trava do backup enquanto o bloco roda, ou recusa.

    E um **bloco**, e nao uma pergunta como o antigo `backup_lock_active()`:
    perguntar "tem backup rodando?" e depois agir deixa aberta a janela
    entre a resposta e a acao -- o backup comeca no meio dela e volta a
    copiar arquivos que estao sendo comprimidos. Segurando a trava durante
    toda a operacao, o backup espera; e enquanto o backup a segura, esta
    operacao nem comeca.

    A trava e a **mesma** do `ops/backup.py`, um advisory lock do proprio
    PostgreSQL (`ops/locks.py`), porque o banco e o unico ponto que o
    processo de backup no host e os processos da aplicacao no container
    enxergam em comum. Um arquivo no volume de midia pareceria mais
    simples e foi o que existiu aqui antes -- so que ninguem o criava.

    Lock de **sessao**, nao de transacao: a compactacao percorre o arquivo
    morto inteiro e prender uma transacao aberta por todo esse tempo
    seguraria o vacuum da base. O `finally` devolve a trava; se o processo
    morrer antes disso, o PostgreSQL a devolve sozinho ao fechar a conexao.
    """
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [BACKUP_LOCK])
        if not cursor.fetchone()[0]:
            raise BackupInProgress(
                f'Backup em andamento; {operacao} nao roda agora.'
            )
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [BACKUP_LOCK])


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
    enough ago, holding the backup lock for the whole pass, respecting the
    20-year record-retention hold, and never touching a file another
    Attachment row still references by storage_key.

    Devolve `(removidos, retidos)`: o segundo são os que a guarda legal
    protegeu, e existe para a passagem ser auditável — uma coleta que
    apaga em silêncio e uma que retém em silêncio parecem iguais no log.
    """
    with backup_exclusive('a coleta de lixo'):
        agora = timezone.now()
        cutoff = agora - timezone.timedelta(days=GC_MIN_AGE_DAYS)
        candidates = (
            Attachment.objects
            .filter(deleted_at__isnull=False, deleted_at__lt=cutoff)
            .exclude(scan_status=AttachmentScanStatus.REJECTED)
            .select_related('patient')
        )

        removed = []
        retidos = []
        # Um paciente costuma ter vários anexos na mesma passada, e cada
        # `retention_expires_at` custa quatro consultas.
        cache_guarda = {}
        # PDF de documento médico nunca sai por aqui, mesmo excluído: o
        # documento continua apontando para ele (auditoria de 2026-10-09,
        # ND-1121-001). A tela de anexos já não deixa excluí-lo; isto é a
        # rede para o que tenha sido excluído antes.
        from .models import MedicalDocument

        de_documento = (
            set(MedicalDocument.objects.exclude(pdf_attachment=None).values_list('pdf_attachment_id', flat=True))
            | set(MedicalDocument.objects.exclude(signed_pdf_attachment=None)
                  .values_list('signed_pdf_attachment_id', flat=True))
        )
        for attachment in candidates:
            if not attachment.storage_key:
                continue
            if attachment.id in de_documento:
                retidos.append(attachment.id)
                continue
            if not eliminacao_permitida(attachment.patient, attachment.classification,
                                        agora=agora, _cache=cache_guarda):
                retidos.append(attachment.id)
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
        if not dry_run and (removed or retidos):
            record_audit_event(
                None, None, 'documents.garbage_collected', outcome='success',
                integrity_metadata={'removed': len(removed), 'held_by_retention': len(retidos)},
            )
        return removed, retidos


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


def _somar_anos(momento, anos):
    """A mesma data, `anos` anos depois — em calendário, não em dias.

    Era `timedelta(days=20 * 365)`, que erra por cinco dias: vinte anos
    contêm cinco bissextos. O erro é para menos, isto é, liberava a
    eliminação cinco dias antes do prazo legal — e o que não pode acontecer
    de jeito nenhum é eliminar prontuário um dia antes da hora.
    """
    try:
        return momento.replace(year=momento.year + anos)
    except ValueError:
        # 29 de fevereiro: o ano de destino não tem esse dia. Cair no 1º de
        # março, e não no 28 de fevereiro, mantém o prazo no mínimo completo.
        return momento.replace(year=momento.year + anos, month=3, day=1)


def retention_expires_at(patient):
    """Quando este prontuário passa a poder ser eliminado, ou `None`."""
    ultimo = last_record_at(patient)
    if ultimo is None:
        return None
    return _somar_anos(ultimo, RETENTION_YEARS)


def eliminacao_permitida(patient, classification, agora=None, _cache=None):
    """Este arquivo pode ser apagado fisicamente do disco?

    A guarda legal existia calculada (`retention_expires_at`) e não era
    consultada por ninguém que apagasse coisa alguma: a coleta de lixo
    olhava só "foi excluído há mais de 30 dias" e removia o arquivo —
    inclusive o exame que compõe um prontuário protegido por vinte anos.
    Excluir na tela é ato de quem opera a clínica; **eliminar** é o que a
    Lei 13.787 condiciona, e as duas coisas não podem ser a mesma.

    Anexo administrativo (comprovante, autorização de convênio) não compõe
    prontuário e segue a regra dos 30 dias. Clínico só sai depois do prazo.

    Sem data de último registro a resposta é não: um paciente sem registro
    nenhum não deveria ter anexo clínico, e quando a premissa de uma regra
    de eliminação não se sustenta, a resposta segura é não eliminar.
    """
    if classification != AttachmentClassification.CLINICAL:
        return True
    if _cache is not None and patient.id in _cache:
        expira = _cache[patient.id]
    else:
        expira = retention_expires_at(patient)
        if _cache is not None:
            _cache[patient.id] = expira
    if expira is None:
        return False
    return (agora or timezone.now()) >= expira


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
