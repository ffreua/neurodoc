"""Segurança e operação: o quarto lote da auditoria de 2026-11-11.

- **login**: o limite por par e-mail+IP que se contornava trocando de IP ou
  de e-mail, a contagem que não era atômica e a espera que prendia o
  processo do `app`;
- **coleta**: o arquivo compartilhado que saía do disco com um anexo
  retido pela guarda de 20 anos ainda apontando para ele;
- **campanhas (LGPD)**: paciente arquivado na lista, o mesmo endereço
  recebendo várias cópias, o descadastro valendo para um contato só;
- **certificado A1**: o titular conferido por uma palavra em qualquer
  ponto do subject;
- **portal**: o nome do paciente no cache do navegador;
- **banco e tarefas**: os tempos limite, o despacho que se acumulava com o
  worker parado, e as tarefas pesadas mortas aos seis minutos.

Tudo dentro de transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_lote_seguranca.py
"""
import datetime
import os
import tempfile
import time
import uuid

from django.conf import settings as dj_settings
from django.core.cache import cache
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

dj_settings.ALLOWED_HOSTS = list(dj_settings.ALLOWED_HOSTS) + ['testserver']
dj_settings.SECURE_SSL_REDIRECT = False

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe != '' else ''))
    if not ok:
        falhas.append(nome)


class _Desfazer(Exception):
    pass


print('=== 1. Login: três contadores, atômicos e sem espera ===')
from accounts import throttling

marca = uuid.uuid4().hex[:8]
ip = f'198.51.100.{int(marca[:2], 16) % 250}'
email = f'alvo-{marca}@roteiro.invalid'
for _ in range(throttling.MAX_ATTEMPTS):
    throttling.register_failure(email, ip)
conferir('cinco erros no par bloqueiam o par', throttling.is_throttled(email, ip))
for n in range(throttling.MAX_POR_CONTA):
    throttling.register_failure(email, f'203.0.113.{n % 250}-{marca}')
conferir('a conta tentada de muitos IPs é bloqueada em qualquer IP',
         throttling.is_throttled(email, f'192.0.2.99-{marca}'))
ip_varredura = f'192.0.2.{int(marca[2:4], 16) % 250}-{marca}'
for n in range(throttling.MAX_POR_IP):
    throttling.register_failure(f'varre-{n}-{marca}@roteiro.invalid', ip_varredura)
conferir('o IP que varre e-mails é bloqueado para qualquer conta',
         throttling.is_throttled(f'outro-{marca}@roteiro.invalid', ip_varredura))
conferir('não existe mais a espera dentro da requisição',
         not hasattr(throttling, 'apply_progressive_delay'))
from accounts.forms import ThrottledAuthenticationForm

inicio = time.monotonic()
ThrottledAuthenticationForm(data={'username': f'novo-{marca}@roteiro.invalid', 'password': 'x' * 12}).is_valid()
conferir('a senha errada é recusada sem segurar o processo', time.monotonic() - inicio < 1.5,
         round(time.monotonic() - inicio, 2))
for chave in list(cache.keys(f'*{marca}*')) if hasattr(cache, 'keys') else []:
    cache.delete(chave)

try:
    with transaction.atomic():
        from documents.models import Attachment, AttachmentClassification
        from documents.retention import GC_MIN_AGE_DAYS, garbage_collect
        from patients.models import Patient, PatientContact, PatientStatus, RegistrationStage
        from tenancy.models import Membership, MembershipStatus, Tenant

        tenant = Tenant.objects.get(slug='demo-clinica-a')

        def paciente(**extra):
            return Patient.objects.create(
                tenant=tenant, full_name=f'ROTEIRO SEGURANCA {uuid.uuid4().hex[:6]}',
                birth_date=datetime.date(1980, 1, 1),
                registration_stage=RegistrationStage.COMPLETE, **extra,
            )

        print('=== 2. Coleta: o arquivo compartilhado com um anexo retido fica ===')
        # Só o ensaio (`dry_run`): a coleta de verdade apagaria arquivos da
        # base de demonstração, e o disco não volta com a transação.
        antigo = timezone.now() - datetime.timedelta(days=GC_MIN_AGE_DAYS + 5)
        com_registro = paciente()
        from clinical.models import Encounter, EncounterKind, EncounterStatus

        medico = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
        ).first()
        Encounter.objects.create(
            tenant=tenant, patient=com_registro, physician_membership=medico, occurred_at=timezone.now(),
            kind=EncounterKind.FREE_TEXT, status=EncounterStatus.FINALIZED, finalized_at=timezone.now(),
            finalized_by=medico,
        )
        fd, compartilhado = tempfile.mkstemp(prefix='roteiro-gc-')
        os.close(fd)

        def anexo(p, chave, classificacao):
            return Attachment.objects.create(
                tenant=tenant, patient=p, storage_key=chave, original_name='termo.pdf',
                mime='application/pdf', bytes=1, sha256='1' * 64, classification=classificacao,
                deleted_at=antigo, deleted_reason='roteiro',
            )

        administrativo = anexo(paciente(), compartilhado, AttachmentClassification.ADMINISTRATIVE)
        retido = anexo(com_registro, compartilhado, AttachmentClassification.CLINICAL)
        fd, sozinho = tempfile.mkstemp(prefix='roteiro-gc-')
        os.close(fd)
        livre = anexo(paciente(), sozinho, AttachmentClassification.ADMINISTRATIVE)
        removidos, retidos = garbage_collect(dry_run=True)
        conferir('o anexo clínico é retido pela guarda', retido.id in retidos)
        conferir('o administrativo que divide o arquivo com ele NÃO é coletado',
                 administrativo.id not in removidos)
        conferir('  e o administrativo com arquivo só dele é (controle)', livre.id in removidos)
        for caminho in (compartilhado, sozinho):
            os.unlink(caminho)

        print('=== 3. Campanhas: ativo, um por endereço, descadastro do endereço ===')
        from communications import marketing
        from communications.models import MarketingCampaign

        endereco = f'mae-{uuid.uuid4().hex[:6]}@roteiro.invalid'
        agora = timezone.now()
        contatos = []
        for _ in range(3):
            contatos.append(PatientContact.objects.create(
                tenant=tenant, patient=paciente(), name='MAE DO ROTEIRO', email=endereco,
                marketing_opt_in_at=agora,
            ))
        arquivado = paciente(status=PatientStatus.ARCHIVED)
        do_arquivado = PatientContact.objects.create(
            tenant=tenant, patient=arquivado, name='CONTATO ARQUIVADO',
            email=f'arq-{uuid.uuid4().hex[:6]}@roteiro.invalid', marketing_opt_in_at=agora,
        )
        elegiveis = set(marketing.eligible_contacts(tenant.id).values_list('id', flat=True))
        conferir('o contato de paciente arquivado fica fora', do_arquivado.id not in elegiveis)
        campanha = MarketingCampaign.objects.create(tenant=tenant, subject='Roteiro', body_text='Texto do roteiro')
        marketing.build_recipients(campanha)
        copias = campanha.recipients.filter(email__iexact=endereco).count()
        conferir('o mesmo endereço recebe uma cópia só', copias == 1, copias)
        marketing.unsubscribe(contatos[1])
        ainda = PatientContact.objects.filter(id__in=[c.id for c in contatos],
                                              marketing_opt_out_at__isnull=True).count()
        conferir('o descadastro vale para todos os contatos com o endereço', ainda == 0, ainda)

        print('=== 4. Certificado A1: o titular pelo nome no CN ===')
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        from documents.credentials import CredentialTitleMismatch, _check_title_holder

        chave = ec.generate_private_key(ec.SECP256R1())

        def certificado(cn, organizacao='CLINICA DA SILVA'):
            nome = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, cn),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, organizacao),
            ])
            agora_cert = datetime.datetime.now(datetime.timezone.utc)
            return (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
                    .public_key(chave.public_key()).serial_number(1)
                    .not_valid_before(agora_cert).not_valid_after(agora_cert + datetime.timedelta(days=1))
                    .sign(chave, hashes.SHA256()))

        def aceita(cn, nome):
            try:
                _check_title_holder(certificado(cn), nome)
                return True
            except CredentialTitleMismatch:
                return False

        conferir('o titular certo passa (nome profissional recortado do nome completo)',
                 aceita('FERNANDO ALBUQUERQUE FREUA:12345678900', 'Dr. Fernando Freua'))
        conferir('outra pessoa com um sobrenome igual é recusada',
                 not aceita('MARIA DA SILVA:12345678900', 'João da Silva'))
        conferir('o nome que só aparece na organização é recusado',
                 not aceita('PEDRO SOUZA:12345678900', 'Ana Silva'))

        print('=== 5. Portal: fora do cache do navegador ===')
        from tenancy.models import ClinicProfile

        perfil = ClinicProfile.objects.filter(tenant=tenant).first()
        if perfil is None:
            print('  (sem perfil da clínica; seção pulada)')
        else:
            ClinicProfile.objects.filter(id=perfil.id).update(patient_portal_enabled=True)
            r = Client().get(f'/solicitacoes/{tenant.slug}/')
            cc = r.headers.get('Cache-Control', '')
            conferir('a página do portal sai no-store', r.status_code < 500 and 'no-store' in cc, (r.status_code, cc))

        raise _Desfazer
except _Desfazer:
    pass

print('=== 6. Banco e tarefas ===')
with connection.cursor() as cursor:
    cursor.execute('SHOW statement_timeout')
    st = cursor.fetchone()[0]
    cursor.execute('SHOW idle_in_transaction_session_timeout')
    it = cursor.fetchone()[0]
conferir('a conexão do site tem tempo limite de consulta', st not in ('0', '0ms'), st)
conferir('e de transação parada', it not in ('0', '0ms'), it)
despacho = dj_settings.CELERY_BEAT_SCHEDULE['events-dispatch-outbox']
conferir('o despacho do beat expira em vez de se acumular', despacho.get('options', {}).get('expires'))
from catalogs import tasks as tarefas_catalogo
from documents import tasks as tarefas_documentos
from reporting import tasks as tarefas_relatorio

for tarefa in (tarefas_relatorio.run_export, tarefas_documentos.compact_archive_task,
               tarefas_documentos.garbage_collect_task, tarefas_catalogo.sincronizar_dominios_descartaveis):
    conferir(f'{tarefa.name} tem limite próprio acima de seis minutos',
             (tarefa.time_limit or 0) > dj_settings.CELERY_TASK_TIME_LIMIT, tarefa.time_limit)
agendada = dj_settings.CELERY_BEAT_SCHEDULE['documents-compact-archive']['schedule']
conferir('a compactação não roda às 03h00, na hora do backup', 3 not in agendada.hour, agendada.hour)

print()
if falhas:
    print(f'FALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('OK: login, coleta, campanhas, certificado, portal, banco e tarefas.')
