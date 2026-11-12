"""O anexo esquecido em quarentena volta a ser verificado (auditoria de 2026-11-11).

`scan_attachment` roda uma vez, no envio. Com o antivírus fora do ar
naquela hora, ou com a fila atrasada além do `expires`, o anexo ficava em
quarentena para sempre — o laudo do portal acendia o alerta e nunca abria.

O roteiro confere a varredura periódica: pega o anexo em quarentena há
mais de quinze minutos; deixa o recém-enviado (a verificação do envio
ainda pode estar rodando), o apagado, o já liberado e o sem arquivo; e
está agendada no beat.

Tudo dentro de transação desfeita; a fila é interceptada.

    docker compose exec -T app python manage.py shell < checks/check_quarentena_retomada.py
"""
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from documents import tasks
from documents.models import Attachment, AttachmentClassification, AttachmentScanStatus
from patients.models import Patient, RegistrationStage
from tenancy.models import Tenant

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


class Desfazer(Exception):
    pass


tenant = Tenant.objects.get(slug='demo-clinica-a')
agora = timezone.now()

try:
    with transaction.atomic():
        paciente = Patient.objects.create(
            tenant=tenant, full_name=f'PACIENTE QUARENTENA {secrets.token_hex(3)}',
            registration_stage=RegistrationStage.COMPLETE,
        )

        def anexo(minutos_atras, **extra):
            a = Attachment.objects.create(
                tenant=tenant, patient=paciente, storage_key=extra.pop('storage_key', '/tmp/roteiro.pdf'),
                original_name='laudo.pdf', mime='application/pdf', bytes=10, sha256='0' * 64,
                classification=AttachmentClassification.CLINICAL, **extra,
            )
            Attachment.objects.filter(id=a.id).update(created_at=agora - timezone.timedelta(minutes=minutos_atras))
            return a

        esquecido = anexo(60)
        recente = anexo(2)
        apagado = anexo(60, deleted_at=agora)
        liberado = anexo(60, scan_status=AttachmentScanStatus.AVAILABLE)
        sem_arquivo = anexo(60, storage_key='')

        enfileirados = []
        original = tasks.scan_attachment.delay
        tasks.scan_attachment.delay = lambda attachment_id: enfileirados.append(attachment_id)
        try:
            tasks.reprocessar_quarentena()
        finally:
            tasks.scan_attachment.delay = original

        print('=== 1. Quem a varredura pega ===')
        conferir('o anexo esquecido em quarentena volta para o antivírus', str(esquecido.id) in enfileirados)
        conferir('o recém-enviado não (a verificação do envio ainda pode rodar)',
                 str(recente.id) not in enfileirados)
        conferir('o apagado não', str(apagado.id) not in enfileirados)
        conferir('o liberado não', str(liberado.id) not in enfileirados)
        conferir('o sem arquivo não', str(sem_arquivo.id) not in enfileirados)

        raise Desfazer
except Desfazer:
    pass

print('=== 2. Está no beat ===')
agendadas = {v['task'] for v in settings.CELERY_BEAT_SCHEDULE.values()}
conferir('reprocessar_quarentena está agendada', 'documents.tasks.reprocessar_quarentena' in agendadas)

print()
if falhas:
    print(f'FALHOU: {len(falhas)} verificação(ões): {falhas}')
    raise SystemExit(1)
print('OK: a quarentena não é mais para sempre.')
