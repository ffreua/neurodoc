"""O relatório da IA aberto pelo sino chega à tela do relatório (1.24.2).

O defeito, como o médico o viu em 2026-10-22: pediu um relatório para o
INSS, saiu da página, e quando o sino avisou, o clique abriu a tela
**genérica** de resultado de IA — "Resumo" e "Hipóteses qualitativas" em
branco, "Informação faltante" vazia. O relatório estava pronto (seis seções,
no banco); só a tela é que não sabia desenhá-lo. Quem ficava na página não
via nada de errado, porque ela se atualiza sozinha no lugar certo — por isso
pareceu que sair da página impedia a IA de terminar.

O roteiro refaz o caminho do clique, sem provedor nenhum (o artefato é
gravado à mão):

- o aviso de um relatório nasce apontando para a tela do relatório;
- o aviso **antigo**, que já está no sino apontando para a genérica, também
  chega lá (redirecionamento);
- a tela genérica não aceita nem rejeita relatório: aprovar é a ponte que
  cria o rascunho do documento, e aceitar por ali o pularia;
- o resumo do atendimento segue indo para a tela genérica, como antes;
- a tela de espera diz que dá para sair.

Tudo em transação desfeita.

    docker compose exec -T app python manage.py shell < checks/check_relatorio_pelo_sino.py
"""
from django.conf import settings
from django.db import transaction
from django.test import Client
from django.urls import reverse

from ai import relatorio, services
from ai.models import AIArtifact, AIJobKind, AIJobStatus, AIReviewState
from ai.tasks import _notify_job_completion
from notifications.models import Notification
from patients.models import Patient
from tenancy.context import AccessContext
from tenancy.models import Membership, MembershipStatus, Tenant

settings.ALLOWED_HOSTS += ['testserver']
settings.SECURE_SSL_REDIRECT = False

falhas = []


def conferir(nome, ok, detalhe=''):
    print(f"  {'ok   ' if ok else 'FALHA'} {nome}" + (f' -> {detalhe}' if not ok and detalhe else ''))
    if not ok:
        falhas.append(nome)


tenant = Tenant.objects.get(slug='demo-clinica-a')
vinculo = Membership.objects.filter(
    tenant=tenant, status=MembershipStatus.ACTIVE, roles__contains=['doctor'],
).select_related('user').first()
ctx = AccessContext(
    user_id=vinculo.user_id, tenant_id=tenant.id, membership_id=vinculo.id,
    permissions=frozenset(vinculo.roles or []), request_id=None,
    tenant_status=tenant.status, capabilities=frozenset(),
)
paciente = Patient.objects.filter(tenant=tenant).order_by('created_at').first()
cliente = Client()
cliente.force_login(vinculo.user)
sessao = cliente.session
sessao['tenant_id'] = str(tenant.id)
sessao.save()

with transaction.atomic():
    job = services.create_job(
        ctx, AIJobKind.PATIENT_REPORT, 'INSS', patient_id=paciente.id,
        target_ref={'finalidade': 'inss', 'pedido': 'relatorio pelo sino',
                    'ref': relatorio.referencia_do_pedido('inss', 'relatorio pelo sino')},
    )
    tela_do_relatorio = reverse('ai:relatorio-detalhe', args=[job.id])

    print('=== 1. Enquanto a IA escreve, a tela diz que dá para sair ===')
    job.status = AIJobStatus.RUNNING
    job.save(update_fields=['status'])
    corpo = cliente.get(tela_do_relatorio).content.decode()
    conferir('a tela de espera diz que dá para sair', 'Pode sair daqui' in corpo)
    conferir('e que o sino avisa', 'o sino avisa quando ficar pronto' in corpo)

    print('=== 2. Pronto: o aviso leva à tela do relatório ===')
    artefato = AIArtifact.objects.create(
        tenant=tenant, job=job, schema_version='v1', provider='roteiro', model='roteiro',
        prompt_version='v3',
        result={'titulo': 'Relatorio Medico para Perito',
                'secoes': [{'titulo': 'Quadro clinico', 'texto': 'Texto que so a tela do relatorio mostra.'}],
                'limitations': 'Baseado no prontuario.'},
    )
    job.status = AIJobStatus.SUCCEEDED
    job.save(update_fields=['status'])
    _notify_job_completion(job)
    aviso = Notification.objects.filter(tenant=tenant, target_id=job.id).first()
    conferir('o aviso existe', aviso is not None)
    conferir('aponta para o relatório, não para a tela genérica',
             aviso is not None and aviso.target_type == 'ai_report', aviso and aviso.target_type)
    conferir('e diz do que se trata', aviso is not None and 'Relatório' in aviso.sanitized_title,
             aviso and aviso.sanitized_title)
    clique = cliente.post(reverse('notifications:open', args=[aviso.id]))
    conferir('o clique no aviso vai para a tela do relatório',
             clique.status_code == 302 and clique['Location'] == tela_do_relatorio,
             (clique.status_code, clique.get('Location')))
    corpo = cliente.get(tela_do_relatorio).content.decode()
    conferir('e a tela mostra o texto do relatório', 'Texto que so a tela do relatorio mostra.' in corpo)

    print('=== 3. O aviso antigo, que já está no sino, também chega lá ===')
    generica = cliente.get(reverse('ai:job-detail', args=[job.id]))
    conferir('a tela genérica encaminha o relatório para a tela dele',
             generica.status_code == 302 and generica['Location'] == tela_do_relatorio,
             (generica.status_code, generica.get('Location')))

    print('=== 4. A tela genérica não aprova nem rejeita relatório ===')
    for rota in ('ai:artifact-accept', 'ai:artifact-reject'):
        resposta = cliente.post(reverse(rota, args=[artefato.id]), {'reason': 'roteiro'})
        artefato.refresh_from_db()
        conferir(f'{rota}: devolve à tela do relatório sem mudar a revisão',
                 resposta.status_code == 302 and resposta['Location'] == tela_do_relatorio
                 and artefato.review_state == AIReviewState.PENDING,
                 (resposta.status_code, resposta.get('Location'), artefato.review_state))

    print('=== 5. O resumo do atendimento segue na tela genérica ===')
    resumo = services.create_job(
        ctx, AIJobKind.PATIENT_SUMMARY, 'roteiro', patient_id=paciente.id,
    )
    resumo.status = AIJobStatus.SUCCEEDED
    resumo.save(update_fields=['status'])
    _notify_job_completion(resumo)
    aviso_resumo = Notification.objects.filter(tenant=tenant, target_id=resumo.id).first()
    conferir('o aviso do resumo continua apontando para a tela genérica',
             aviso_resumo is not None and aviso_resumo.target_type == 'ai_job',
             aviso_resumo and aviso_resumo.target_type)
    conferir('e ela abre', cliente.get(reverse('ai:job-detail', args=[resumo.id])).status_code == 200)

    transaction.set_rollback(True)

if falhas:
    print(f'\nFALHA: {len(falhas)} — ' + '; '.join(falhas))
    raise SystemExit(1)
print('\nOK: o relatório aberto pelo sino chega à tela do relatório.')
