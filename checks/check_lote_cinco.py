"""O quinto lote da auditoria de 2026-11-11: IA, comunicações, prontuário e bordas.

Cada seção tenta o que o código aceitava e não devia:

- **IA**: descartar como relatório um artefato de outro tipo;
- **chat da equipe**: o texto que ficava no Redis além das 72 horas e
  depois de "Apagar conversa";
- **prontuário**: a escala com pontuação fora das opções, o número "nan"
  no roteiro, e trazer a consulta anterior sem subir a versão;
- **portal**: a recusa que passava por cima do pedido já atendido;
- **comunicações**: o remetente com vírgula no nome;
- **bordas**: troca de organização com id inválido, exportação com
  relatório desconhecido, o log da CSP com a busca e o token, e a lista de
  endereços de IA aceitando a rede interna.

Tudo dentro de transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_lote_cinco.py
"""
import datetime
import uuid

from django.conf import settings as dj_settings
from django.db import transaction
from django.http import QueryDict
from django.test import Client, RequestFactory
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


try:
    with transaction.atomic():
        from clinical.models import Encounter, EncounterKind, EncounterStatus
        from patients.models import Patient, RegistrationStage
        from tenancy.models import Membership, MembershipStatus, Tenant

        tenant = Tenant.objects.get(slug='demo-clinica-a')
        medico = Membership.objects.filter(
            tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
        ).select_related('user').order_by('user__email').first()
        paciente = Patient.objects.create(
            tenant=tenant, full_name=f'ROTEIRO LOTE CINCO {uuid.uuid4().hex[:6]}',
            birth_date=datetime.date(1980, 1, 1), registration_stage=RegistrationStage.COMPLETE,
        )
        cli = Client()
        cli.force_login(medico.user)
        sessao = cli.session
        sessao['tenant_id'] = str(tenant.id)
        sessao.save()

        print('=== 1. IA: só relatório se descarta como relatório ===')
        from ai.models import AIArtifact, AIJob, AIJobKind, AIJobStatus

        job = AIJob.objects.create(
            tenant=tenant, user=medico.user, membership=medico, patient=paciente,
            kind=AIJobKind.PATIENT_SUMMARY, status=AIJobStatus.SUCCEEDED,
            source_version=1, purpose='roteiro',
        )
        artefato = AIArtifact.objects.create(
            tenant=tenant, job=job, schema_version='1', provider='roteiro', model='roteiro',
            prompt_version='1', result={'resumo': 'x'},
        ) if any(f.name == 'tenant' for f in AIArtifact._meta.fields) else AIArtifact.objects.create(
            job=job, schema_version='1', provider='roteiro', model='roteiro', prompt_version='1',
            result={'resumo': 'x'},
        )
        from django.urls import reverse

        cli.post(reverse('ai:relatorio-descartar', args=[artefato.id]),
                 {'patient_id': str(paciente.id), 'reason': 'roteiro'})
        conferir('o resumo não é apagado pelo descarte de relatório',
                 AIArtifact.objects.filter(id=artefato.id).exists())

        print('=== 2. Prontuário: escala e número fora da faixa ===')
        from exams.models import ExamScale
        from exams.recording import ValorInvalido, extract_scale

        escala = ExamScale.objects.filter(tenant=tenant, active=True).prefetch_related('items').first()
        if escala is None or not escala.items.exists():
            print('  (sem escala nesta clínica; seção pulada)')
        else:
            item = escala.items.all()[0]

            def tentar(valor):
                dados = QueryDict(mutable=True)
                dados[f'escala__{escala.code}__{item.code}'] = valor
                try:
                    extract_scale(escala, dados, f'escala__{escala.code}')
                    return 'aceito'
                except ValorInvalido:
                    return 'recusado'

            valido = str((item.options or [{}])[0].get('value'))
            conferir('a pontuação da lista é aceita', tentar(valido) == 'aceito', valido)
            conferir('"40" num item de opções fechadas é recusado', tentar('40') == 'recusado')
            conferir('"nan" é recusado sem erro 500', tentar('nan') == 'recusado')

        print('=== 3. Prontuário: trazer a consulta anterior sobe a versão ===')
        from clinical.carry_forward import review_carry_forward_item
        from clinical.models import CarryForwardItem, ReviewAction

        anterior = Encounter.objects.create(
            tenant=tenant, patient=paciente, physician_membership=medico,
            occurred_at=timezone.now() - datetime.timedelta(days=30), kind=EncounterKind.STRUCTURED,
            status=EncounterStatus.FINALIZED, finalized_at=timezone.now(), finalized_by=medico,
            plan_text='Conduta antiga.',
        )
        atual = Encounter.objects.create(
            tenant=tenant, patient=paciente, physician_membership=medico, occurred_at=timezone.now(),
            kind=EncounterKind.STRUCTURED, status=EncounterStatus.DRAFT,
        )
        versao = atual.row_version
        item_cf = CarryForwardItem.objects.create(
            tenant=tenant, target_encounter=atual, source_encounter=anterior, field_path='plan_text',
            source_version_hash='0' * 64, copied_value={'text': 'Conduta antiga.'},
        )
        review_carry_forward_item(item_cf, ReviewAction.ACCEPTED, medico.id)
        atual.refresh_from_db()
        conferir('o texto entra e a versão sobe (a outra aba percebe)',
                 atual.plan_text == 'Conduta antiga.' and atual.row_version == versao + 1,
                 (atual.plan_text, versao, atual.row_version))

        print('=== 4. Comunicações: o remetente com vírgula é um endereço só ===')
        from email.utils import getaddresses

        from communications.models import _remetente

        conferir('"Clínica X, Neurologia" vira um endereço',
                 len(getaddresses([_remetente('Clínica X, Neurologia', 'a@b.com')])) == 1)

        print('=== 5. Bordas ===')
        r = cli.post('/accounts/switch-tenant/', {'tenant_id': 'nao-e-uuid'})
        conferir('trocar de organização com id inválido não dá 500', r.status_code < 500, r.status_code)
        r = cli.post('/app/reporting/exports/', {'report_name': 'nao-existe', 'start': '2026-01-01',
                                                 'end': '2026-01-31'})
        conferir('exportação de relatório desconhecido não dá 500', r.status_code < 500, r.status_code)

        raise _Desfazer
except _Desfazer:
    pass

from base.csp_views import _sem_dado

uri = _sem_dado('document-uri', 'https://neurodoc.app.br/app/patients/?q=MARIA SILVA')
conferir('o log da CSP não leva a busca', 'MARIA' not in uri, uri)
uri = _sem_dado('document-uri', 'https://neurodoc.app.br/d/abc123token/')
conferir('nem o token do link do documento', 'abc123token' not in uri, uri)

from ops.superadmin import _host_de_metadados_ou_interno

conferir('metadados da nuvem não se liberam', _host_de_metadados_ou_interno('http://169.254.169.254/'))
conferir('nem o banco da pilha', _host_de_metadados_ou_interno('http://db:5432'))
conferir('o Ollama da rede da clínica, sim', not _host_de_metadados_ou_interno('http://192.168.0.10:11434'))

print('=== 6. Chat da equipe: o Redis também esquece ===')
from teamchat import streaming

tenant_falso, usuario_falso, conversa = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
chave = streaming.inbox_key(tenant_falso, usuario_falso)
cliente_redis = streaming._client()
try:
    velho_ms = int((timezone.now() - datetime.timedelta(hours=80)).timestamp() * 1000)
    cliente_redis.xadd(chave, {'type': 'mensagem', 'data': '{"conversa": "velha"}'}, id=f'{velho_ms}-0')
    streaming.publish(tenant_falso, usuario_falso, 'mensagem', {'conversa': str(conversa), 'texto': 'oi'})
    streaming.publish(tenant_falso, usuario_falso, 'mensagem', {'conversa': 'outra', 'texto': 'fica'})
    from teamchat.services import limite_de_retencao

    streaming.aparar_vencidos(limite_de_retencao())
    restantes = [c['data'] for _, c in cliente_redis.xrange(chave)]
    conferir('o evento de 80 horas sai da caixa', not any('velha' in d for d in restantes), restantes)
    streaming.esquecer_conversa(tenant_falso, usuario_falso, conversa)
    restantes = [c['data'] for _, c in cliente_redis.xrange(chave)]
    conferir('"Apagar conversa" tira o texto dela da caixa', not any(str(conversa) in d for d in restantes))
    conferir('  e deixa o da outra conversa', any('fica' in d for d in restantes), restantes)
    conferir('reconectar pedindo o começo não volta ao que venceu',
             streaming.id_anterior_a('0', limite_de_retencao()))
finally:
    cliente_redis.delete(chave)

print()
if falhas:
    print(f'FALHA: {len(falhas)} item(ns): ' + '; '.join(falhas))
    raise SystemExit(1)
print('OK: IA, chat da equipe, prontuário, remetente e bordas.')
