"""Console do superadministrador da instalação.

Quem opera o servidor precisa responder a perguntas que nenhuma tela da
clínica responde: quantas organizações existem, quem tem conta, se a fila
está andando, se o banco responde, e — a mais importante — quem fez o quê
no sistema inteiro.

**Só leitura, e nunca conteúdo clínico.**

Esta é a decisão que governa o arquivo. A tentação óbvia seria dar ao
superadministrador uma visão de tudo, prontuário incluído; e um sistema em
que o sigilo médico depende da disciplina de quem hospeda o servidor não é
um sistema com sigilo médico. Auditar é saber *quem fez o quê*, não ler o
que foi escrito — e `AuditEvent` foi desenhado exatamente assim: guarda
ação, ator, organização, objeto e desfecho, e nunca texto de prontuário.

Por isso a trilha aqui mostra `documents.medicaldocument_created` com o
identificador do documento, e não a receita. Para ler o prontuário de um
paciente continua sendo preciso ter vínculo clínico naquela clínica, o que
aparece na própria trilha.

O que exige escrita — criar usuário, mudar senha, corrigir dado — continua
no admin técnico do Django (`/admin/`), que já registra cada alteração em
`LogEntry`. Este console não duplica aquilo; ele aponta para lá.

Acesso: `is_superuser` **e** MFA verificada, a mesma exigência dos painéis
técnicos (`base.middleware.TechnicalPanelMFAMiddleware`). Um console que
lê a trilha de auditoria da instalação inteira atrás de senha só seria uma
credencial roubada de distância do histórico de todas as clínicas.
"""

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import View

PAGE_SIZE = 100


class SuperAdminView(LoginRequiredMixin, View):
    """Base: superusuário com MFA verificada, ou 404.

    404 e não 403 pela razão já adotada no resto do sistema: quem não pode
    entrar não precisa saber que a tela existe.

    A verificação é feita aqui e não confiada ao middleware dos painéis
    técnicos, que só cobre os prefixos `/admin/dj-*`. Uma tela nova sob
    outro caminho nasceria desprotegida.
    """

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not (user.is_authenticated and user.is_active
                and user.is_superuser and user.is_verified()):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _nav(active):
    return {'nav_active': active}


# ------------------------------------------------------------------ visão geral

def _database_facts():
    """Versão do Postgres e tamanho do banco.

    Uma consulta, e não `pg_stat_*` inteiro: o que se quer saber ao abrir a
    página é se o banco responde e quanto ele já ocupa. O resto está no
    painel técnico.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT version(), pg_database_size(current_database())')
            version, size = cursor.fetchone()
        return {
            'ok': True,
            'version': version.split(' on ')[0],
            'size_mb': round(size / (1024 * 1024), 1),
        }
    except Exception as exc:                                # noqa: BLE001
        # Falha de banco não pode derrubar a página que existe para
        # diagnosticar falha de banco.
        return {'ok': False, 'error': str(exc)[:200]}


def _broker_facts():
    from ops import runtime

    return {
        'redis': _probe(runtime.redis_ready),
        'broker': _probe(runtime.broker_ready),
    }


def _probe(check):
    try:
        return {'ok': bool(check())}
    except Exception as exc:                                # noqa: BLE001
        return {'ok': False, 'error': str(exc)[:200]}


def _celery_facts():
    """Filas e tarefas periódicas, pelo que o Celery reporta.

    Tolerante a worker fora do ar de propósito: a página serve para
    descobrir que ele está fora, e uma exceção aqui daria 500 justamente
    no momento em que a informação é necessária.
    """
    try:
        from core.celery import app as celery_app

        inspector = celery_app.control.inspect(timeout=1.5)
        active = inspector.active() or {}
        scheduled = inspector.scheduled() or {}
        registered = inspector.registered() or {}
        return {
            'ok': bool(active or registered),
            'workers': sorted(set(active) | set(registered)),
            'active': sum(len(v) for v in active.values()),
            'scheduled': sum(len(v) for v in scheduled.values()),
        }
    except Exception as exc:                                # noqa: BLE001
        return {'ok': False, 'error': str(exc)[:200]}


class OverviewView(SuperAdminView):
    def get(self, request):
        from accounts.models import User
        from audit.models import AuditEvent
        from documents.models import MedicalDocument
        from patients.models import Patient
        from tenancy.models import Membership, MembershipStatus, Tenant

        agora = timezone.now()
        dia = agora - timezone.timedelta(days=1)
        context = _nav('overview')
        context.update({
            'release_id': settings.RELEASE_ID,
            'debug': settings.DEBUG,
            'public_base_url': settings.PUBLIC_BASE_URL,
            # As chaves não aparecem — só se estão configuradas. Um console
            # que exibisse credencial transformaria a sessão do
            # superadministrador na chave-mestra de todas as integrações.
            'flags': [
                ('E-mail (instalação)', settings.EMAIL_ENABLED),
                ('SMS (instalação)', settings.SMS_ENABLED),
                ('IA (instalação)', settings.AI_ENABLED),
                ('Chave-mestra de segredos', bool(settings.SECRETS_MASTER_KEY)),
            ],
            'database': _database_facts(),
            'celery': _celery_facts(),
            'counts': {
                'tenants': Tenant.objects.count(),
                'users': User.objects.count(),
                'memberships': Membership.objects.filter(status=MembershipStatus.ACTIVE).count(),
                'patients': Patient.objects.count(),
                'documents': MedicalDocument.objects.count(),
                'audit_day': AuditEvent.objects.filter(created_at__gte=dia).count(),
                'audit_denied_day': AuditEvent.objects.filter(
                    created_at__gte=dia, outcome='denied',
                ).count(),
            },
            'docs_enabled': settings.NEURODOC_DOCS_ENABLED,
        })
        context.update(_broker_facts())
        return render(request, 'ops/superadmin/overview.html', context)


# ---------------------------------------------------------------- organizações

class TenantsView(SuperAdminView):
    def get(self, request):
        from tenancy.models import MembershipStatus, Tenant

        linhas = (
            Tenant.objects.annotate(
                member_count=Count(
                    'membership', filter=Q(membership__status=MembershipStatus.ACTIVE), distinct=True,
                ),
                patient_count=Count('patient', distinct=True),
            ).order_by('legal_name')
        )
        context = _nav('tenants')
        context['rows'] = list(linhas)
        return render(request, 'ops/superadmin/tenants.html', context)


# -------------------------------------------------------------------- usuários

class UsersView(SuperAdminView):
    """Todas as contas da instalação, com os vínculos de cada uma.

    Atravessa organizações de propósito — é o único lugar do sistema que
    atravessa. Sem ele não há como responder "esta pessoa tem acesso a
    quais clínicas?", que é a pergunta que se faz quando alguém sai da
    empresa.
    """

    def get(self, request):
        from accounts.models import User

        termo = (request.GET.get('q') or '').strip()
        usuarios = User.objects.prefetch_related('memberships__tenant').order_by('email')
        if termo:
            usuarios = usuarios.filter(
                Q(email__icontains=termo) | Q(first_name__icontains=termo)
                | Q(last_name__icontains=termo)
            )
        context = _nav('users')
        context.update({
            'rows': list(usuarios[:PAGE_SIZE]),
            'q': termo,
            'truncated': usuarios.count() > PAGE_SIZE,
            'page_size': PAGE_SIZE,
        })
        return render(request, 'ops/superadmin/users.html', context)


# ------------------------------------------------------------------- auditoria

class AuditView(SuperAdminView):
    """A trilha da instalação inteira, filtrável.

    O filtro por desfecho existe porque `denied` é o que se procura
    primeiro: uma sequência de negações do mesmo ator é tentativa de
    alcançar o que não lhe compete, e ela se perde no meio de milhares de
    `success` se não houver como isolá-la.
    """

    def get(self, request):
        from accounts.models import User
        from audit.models import AuditEvent, AuditOutcome
        from tenancy.models import Tenant

        eventos = AuditEvent.objects.select_related('actor', 'tenant').order_by('-created_at')

        tenant_id = (request.GET.get('tenant') or '').strip()
        actor_id = (request.GET.get('actor') or '').strip()
        outcome = (request.GET.get('outcome') or '').strip()
        action = (request.GET.get('action') or '').strip()
        since = (request.GET.get('since') or '').strip()

        if tenant_id:
            eventos = eventos.filter(tenant_id=tenant_id)
        if actor_id:
            eventos = eventos.filter(actor_id=actor_id)
        if outcome in dict(AuditOutcome.choices):
            eventos = eventos.filter(outcome=outcome)
        if action:
            eventos = eventos.filter(action__icontains=action)
        if since:
            parsed = timezone.datetime.fromisoformat(since) if _is_iso_date(since) else None
            if parsed is not None:
                eventos = eventos.filter(created_at__gte=timezone.make_aware(parsed))

        context = _nav('audit')
        context.update({
            'rows': list(eventos[:PAGE_SIZE]),
            'total': eventos.count(),
            'page_size': PAGE_SIZE,
            'tenants': list(Tenant.objects.order_by('legal_name')),
            'actors': list(
                User.objects.filter(audit_events__isnull=False).distinct().order_by('email')[:200]
            ),
            'outcomes': AuditOutcome.choices,
            'filters': {
                'tenant': tenant_id, 'actor': actor_id, 'outcome': outcome,
                'action': action, 'since': since,
            },
        })
        return render(request, 'ops/superadmin/audit.html', context)


def _is_iso_date(value):
    try:
        timezone.datetime.fromisoformat(value)
        return True
    except ValueError:
        return False
