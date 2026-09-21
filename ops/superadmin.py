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

**Duas escritas, e so duas** (setembro/2026): emitir convite de plataforma
e mudar o plano de uma organizacao. As duas sao atos comerciais sobre a
instalacao, nao sobre pacientes, e nao existem em nenhuma outra tela -
quem vende e quem opera o servidor. Cada uma exige motivo e grava
`AuditEvent`.

O resto do que exige escrita - criar usuario, mudar senha, corrigir dado -
continua no admin tecnico do Django (`/admin/`), que ja registra cada
alteracao em `LogEntry`. Este console nao duplica aquilo; ele aponta para
la. E nenhuma das duas escritas toca em prontuario, que e a linha que o
arquivo inteiro protege.

Acesso: `is_superuser` **e** MFA verificada, a mesma exigência dos painéis
técnicos (`base.middleware.TechnicalPanelMFAMiddleware`). Um console que
lê a trilha de auditoria da instalação inteira atrás de senha só seria uma
credencial roubada de distância do histórico de todas as clínicas.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

PAGE_SIZE = 100

#: Quantos nomes de organizacao o aviso de "sem contrato" imprime antes de
#: virar um numero. Doze cabe em duas linhas; acima disso o aviso deixa de
#: ser aviso e vira lista.
NOMES_VISIVEIS = 12


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

def _avisos_de_seguranca():
    """O que está frouxo nesta instalação, dito onde alguém vai ler.

    Todos estes são estados legítimos em algum momento da vida de uma
    instalação — e nenhum deles deveria durar. `SECURE_HSTS_SECONDS`
    começa em `0` de propósito, porque o navegador **guarda** a instrução
    e ligá-la antes de o HTTPS funcionar deixa o site inalcançável para
    quem já visitou, sem desfazer pelo servidor. O problema não é o valor
    inicial: é que nada nunca lembra de trocá-lo, e uma instalação segue
    anos sem HSTS porque o dia de ligar não chegou na lista de ninguém.

    Só aparece o que está errado. Uma tela que lista vinte itens verdes e
    um vermelho é uma tela em que ninguém vê o vermelho.
    """
    avisos = []
    https = str(settings.PUBLIC_BASE_URL or '').startswith('https://')

    if settings.DEBUG:
        avisos.append({
            'titulo': 'Modo de depuração ligado',
            'texto': (
                'Com DEBUG=True qualquer erro mostra a configuração e trechos do '
                'código a quem provocou o erro. Nunca em produção.'
            ),
            'acao': 'DEBUG=False no .env, e publique de novo.',
            'grave': True,
        })

    # Sem HTTPS a instrução não se aplica: é o ambiente local, onde o
    # valor 0 é o certo e o aviso seria ruído permanente.
    if https and not settings.SECURE_HSTS_SECONDS:
        avisos.append({
            'titulo': 'HSTS desligado',
            'texto': (
                'O site responde em HTTPS, mas não manda o navegador exigir HTTPS nas '
                'próximas visitas. Quem digitar o endereço sem "https://" numa rede '
                'hostil pode ser levado a uma cópia em HTTP sem perceber.'
            ),
            'acao': (
                'Depois de confirmar que o cadeado aparece sem aviso: '
                'SECURE_HSTS_SECONDS=31536000 no .env e publique de novo. '
                'O navegador guarda a instrução — ligue só quando o HTTPS estiver '
                'comprovadamente funcionando, porque voltar atrás não depende de nós.'
            ),
            'grave': False,
        })
    elif https and settings.SECURE_HSTS_SECONDS and not settings.SECURE_HSTS_INCLUDE_SUBDOMAINS:
        avisos.append({
            'titulo': 'HSTS não cobre os subdomínios',
            'texto': (
                'O domínio principal exige HTTPS; um subdomínio, não. A instalação usa '
                'subdomínio por clínica como alias.'
            ),
            'acao': 'SECURE_HSTS_INCLUDE_SUBDOMAINS=True, depois de conferir que todos servem HTTPS.',
            'grave': False,
        })

    if not settings.SECRETS_MASTER_KEY:
        avisos.append({
            'titulo': 'Chave-mestra de segredos ausente',
            'texto': (
                'Sem ela a clínica não consegue guardar as próprias credenciais de '
                'e-mail e SMS — o campo aceita, e o envio falha depois.'
            ),
            'acao': 'Grave o secret NEURODOC_SECRETS_MASTER_KEY e publique de novo.',
            'grave': True,
        })

    return avisos


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
                # O estado do HSTS ao lado dos outros interruptores, e nao
                # so no aviso: quem vem conferir a instalacao procura a
                # linha, e um aviso que sumiu depois de resolvido nao
                # responde "esta ligado?".
                ('HSTS (HTTPS obrigatório no navegador)', bool(settings.SECURE_HSTS_SECONDS)),
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
            'avisos': _avisos_de_seguranca(),
        })
        context.update(_broker_facts())
        return render(request, 'ops/superadmin/overview.html', context)


# ---------------------------------------------------------------- organizações

class TenantsView(SuperAdminView):
    """As organizacoes da instalacao, com uso contra limite do plano.

    O uso ao lado do limite e o que torna a troca de plano uma decisao em
    vez de um palpite: rebaixar uma clinica para um teto abaixo do que ela
    ja usa e legitimo - nada some, ela so para de crescer -, mas e preciso
    **ver** que e isso que vai acontecer antes de confirmar.
    """

    def get(self, request):
        from tenancy import limits
        from tenancy.models import MembershipStatus, Tenant, TenantStatus
        from tenancy.plans import PLANS, PUBLIC_ORDER

        linhas = []
        for tenant in Tenant.objects.annotate(
            member_count=Count(
                'membership', filter=Q(membership__status=MembershipStatus.ACTIVE), distinct=True,
            ),
        ).order_by('legal_name'):
            linhas.append({
                'obj': tenant,
                'patients': limits.patient_status(tenant),
                'doctors': limits.doctor_status(tenant),
            })
        context = _nav('tenants')
        context['rows'] = linhas
        context['statuses'] = [
            {'code': str(code), 'label': rotulo} for code, rotulo in TenantStatus.choices
        ]
        context['plans'] = [
            {'code': str(code), 'label': PLANS[code]['label'],
             'patients': limits.describe_limit(PLANS[code]['max_patients']),
             'doctors': limits.describe_limit(PLANS[code]['max_doctors'])}
            for code in PUBLIC_ORDER
        ]
        return render(request, 'ops/superadmin/tenants.html', context)


class TenantPlanView(SuperAdminView):
    """Troca o plano de uma organizacao que ja existe.

    Exige motivo escrito. Um plano trocado sem motivo e indistinguivel de
    um erro seis meses depois, e a pergunta que se faz entao - "por que
    esta clinica tem 1.200 pacientes?" - nao tem outra fonte: o e-mail que
    combinou se perdeu, e quem combinou pode nao estar mais aqui.

    Nunca apaga nem esconde nada. Rebaixar abaixo do uso corrente e
    permitido e **congela**: os registros continuam acessiveis, e o
    sistema apenas recusa o proximo. E a regra da Entrega 1, e ela vale
    daqui tambem.
    """

    def post(self, request, tenant_id):
        from audit.services import record_audit_event
        from tenancy.models import Tenant
        from tenancy.plans import PLANS

        tenant = get_object_or_404(Tenant, id=tenant_id)
        plano = request.POST.get('plan', '')
        motivo = (request.POST.get('plan_note') or '').strip()

        if plano not in PLANS:
            messages.error(request, 'Plano desconhecido.')
            return redirect('superadmin:tenants')
        if not motivo:
            messages.error(
                request,
                'Escreva o motivo da troca. E o que responde "por que esta clinica '
                'tem este plano?" quando alguem perguntar depois.',
            )
            return redirect('superadmin:tenants')

        def _inteiro(campo):
            """Vazio e nulo (usa o plano); zero e zero.

            `int(valor or 0)` transformaria o campo em branco em zero, que
            e um limite legitimo - e travaria a clinica inteira por um
            campo que a pessoa so nao preencheu.
            """
            bruto = (request.POST.get(campo) or '').strip()
            if not bruto:
                return None
            valor = int(bruto)
            if valor < 0:
                raise ValueError('Limite nao pode ser negativo.')
            return valor

        try:
            pacientes = _inteiro('patient_limit_override')
            medicos = _inteiro('doctor_limit_override')
        except ValueError:
            messages.error(request, 'Os limites devem ser numeros inteiros, ou ficar em branco.')
            return redirect('superadmin:tenants')

        anterior = {
            'plan': tenant.plan,
            'patient_limit_override': tenant.patient_limit_override,
            'doctor_limit_override': tenant.doctor_limit_override,
        }
        tenant.plan = plano
        tenant.patient_limit_override = pacientes
        tenant.doctor_limit_override = medicos
        tenant.plan_note = motivo[:255]
        tenant.full_clean()
        tenant.save(update_fields=[
            'plan', 'patient_limit_override', 'doctor_limit_override', 'plan_note', 'updated_at',
        ])
        record_audit_event(
            request.user, tenant, 'tenancy.tenant_plan_changed',
            object_type='tenant', object_id=tenant.id, outcome='success',
            integrity_metadata={
                'from': anterior,
                'to': {'plan': tenant.plan,
                       'patient_limit_override': tenant.patient_limit_override,
                       'doctor_limit_override': tenant.doctor_limit_override},
                # O motivo entra na trilha: e administrativo, nunca clinico.
                'note': tenant.plan_note,
            },
        )
        messages.success(request, f'Plano de {tenant.legal_name} atualizado.')
        return redirect('superadmin:tenants')


class TenantStatusView(SuperAdminView):
    """Suspende, encerra ou reativa uma organizacao. Nunca apaga.

    Sao dois desligamentos diferentes, e a diferenca importa:

    `suspended` e a falta de pagamento. A clinica **congela** -- todo mundo
    continua entrando, lendo prontuario, imprimindo e exportando, e nada e
    criado nem alterado. Cortar o acesso do medico ao registro dos proprios
    pacientes por um boleto atrasado transformaria uma questao comercial num
    problema de assistencia, e o prontuario tem guarda de vinte anos que nao
    e do sistema decidir interromper.

    `closed` e a rescisao. A porta fecha e a tela explica a quem recorrer.
    O dado **continua no banco**: encerrar contrato nao e apagar arquivo.

    Exige motivo escrito, como a troca de plano. "Por que esta clinica esta
    suspensa?" seis meses depois nao tem outra fonte -- o e-mail que
    combinou se perdeu, e quem combinou pode nao estar mais aqui.
    """

    def post(self, request, tenant_id):
        from django.utils import timezone

        from audit.services import record_audit_event
        from tenancy.models import Tenant, TenantStatus

        tenant = get_object_or_404(Tenant, id=tenant_id)
        estado = request.POST.get('status', '')
        motivo = (request.POST.get('status_note') or '').strip()

        if estado not in TenantStatus.values:
            messages.error(request, 'Estado desconhecido.')
            return redirect('superadmin:tenants')
        if estado == tenant.status:
            messages.info(request, f'{tenant.legal_name} ja esta neste estado.')
            return redirect('superadmin:tenants')
        if not motivo:
            messages.error(
                request,
                'Escreva o motivo. E o que responde "por que esta clinica esta '
                'assim?" quando alguem perguntar depois.',
            )
            return redirect('superadmin:tenants')

        anterior = tenant.status
        tenant.status = estado
        tenant.status_note = motivo[:255]
        tenant.status_changed_at = timezone.now()
        tenant.full_clean()
        tenant.save(update_fields=['status', 'status_note', 'status_changed_at', 'updated_at'])
        record_audit_event(
            request.user, tenant, 'tenancy.tenant_status_changed',
            object_type='tenant', object_id=tenant.id, outcome='success',
            integrity_metadata={
                'from': anterior, 'to': tenant.status,
                # O motivo entra na trilha: e administrativo, nunca clinico.
                'note': tenant.status_note,
            },
        )
        rotulo = dict(TenantStatus.choices)[estado]
        messages.success(request, f'{tenant.legal_name}: {rotulo}.')
        return redirect('superadmin:tenants')


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


# ------------------------------------------------------------------ convites

class InvitationsView(SuperAdminView):
    """Convites de plataforma: emitir, ver os pendentes, revogar.

    O convite de plataforma e o unico caminho para uma organizacao nascer,
    e agora ele carrega o plano contratado. Emitir era so um comando de
    linha (`issue_platform_invitation`), o que serve a quem esta com uma
    sessao aberta no servidor e nao a quem acabou de fechar uma venda pelo
    telefone.

    **O token aparece uma vez.** Guardamos o hash, nunca o valor: um
    convite legivel na tela depois de emitido seria um convite legivel por
    quem tivesse acesso de leitura ao banco. Perdido o token, revoga-se e
    emite-se outro - que e mais barato do que a alternativa.
    """

    def get(self, request, emitido=None):
        from tenancy.limits import describe_limit, granted_limits
        from tenancy.models import Invitation, InvitationPurpose
        from tenancy.plans import PLANS, PUBLIC_ORDER

        agora = timezone.now()
        pendentes = (
            Invitation.objects
            .filter(purpose=InvitationPurpose.PLATFORM, consumed_at__isnull=True,
                    revoked_at__isnull=True, expires_at__gt=agora)
            .select_related('issued_by').order_by('-created_at')
        )
        usados = (
            Invitation.objects
            .filter(purpose=InvitationPurpose.PLATFORM)
            .exclude(consumed_at__isnull=True, revoked_at__isnull=True, expires_at__gt=agora)
            .select_related('issued_by', 'consumed_by').order_by('-created_at')[:25]
        )

        def _linha(invitation):
            pacientes, medicos = granted_limits(
                invitation.plan, invitation.patient_limit_override,
                invitation.doctor_limit_override,
            )
            return {
                'obj': invitation,
                'plan_label': PLANS.get(invitation.plan, {}).get('label', invitation.plan),
                'patients': describe_limit(pacientes),
                'doctors': describe_limit(medicos),
            }

        context = _nav('invitations')
        context.update({
            'pending': [_linha(i) for i in pendentes],
            'history': [_linha(i) for i in usados],
            'plans': [
                {'code': str(code), 'label': PLANS[code]['label'],
                 'patients': describe_limit(PLANS[code]['max_patients']),
                 'doctors': describe_limit(PLANS[code]['max_doctors'])}
                for code in PUBLIC_ORDER
            ],
            'emitido': emitido,
        })
        return render(request, 'ops/superadmin/invitations.html', context)

    def post(self, request):
        from audit.services import record_audit_event
        from tenancy.invitations import issue_invitation
        from tenancy.models import InvitationPurpose
        from tenancy.plans import PLANS

        plano = request.POST.get('plan', '')
        if plano not in PLANS:
            messages.error(request, 'Escolha um plano.')
            return redirect('superadmin:invitations')

        def _inteiro(campo):
            # Vazio e nulo (usa o plano); zero e zero. Ver `TenantPlanView`.
            bruto = (request.POST.get(campo) or '').strip()
            if not bruto:
                return None
            valor = int(bruto)
            if valor < 0:
                raise ValueError
            return valor

        try:
            pacientes = _inteiro('patient_limit_override')
            medicos = _inteiro('doctor_limit_override')
            dias = int((request.POST.get('ttl_days') or '7').strip())
        except ValueError:
            messages.error(request, 'Limites e prazo devem ser numeros inteiros.')
            return redirect('superadmin:invitations')
        if not 1 <= dias <= 90:
            messages.error(request, 'O prazo deve ficar entre 1 e 90 dias.')
            return redirect('superadmin:invitations')

        invitation, raw_token = issue_invitation(
            InvitationPurpose.PLATFORM, issued_by=request.user,
            email_binding=(request.POST.get('email_binding') or '').strip(),
            ttl_days=dias, plan=plano,
            patient_limit_override=pacientes, doctor_limit_override=medicos,
            plan_note=(request.POST.get('plan_note') or '').strip(),
        )
        record_audit_event(
            request.user, None, 'tenancy.platform_invitation_issued',
            object_type='invitation', object_id=invitation.id, outcome='success',
            integrity_metadata={
                'plan': invitation.plan,
                'patient_limit_override': invitation.patient_limit_override,
                'doctor_limit_override': invitation.doctor_limit_override,
                'email_binding': invitation.email_binding,
            },
        )
        # O token vai para a tela uma vez, pelo `get` abaixo - e nao pela
        # sessao nem por `messages`, que o gravariam em Redis e no cookie.
        return self.get(request, emitido=raw_token)


class InvitationRevokeView(SuperAdminView):
    def post(self, request, invitation_id):
        from audit.services import record_audit_event
        from tenancy.models import Invitation, InvitationPurpose

        invitation = get_object_or_404(
            Invitation, id=invitation_id, purpose=InvitationPurpose.PLATFORM,
        )
        if invitation.consumed_at is not None:
            # Revogar o que ja virou clinica nao desfaz a clinica, e daria a
            # impressao de que desfez. Para mexer no que ja existe, o
            # caminho e a troca de plano em Organizacoes.
            messages.error(
                request,
                'Este convite ja foi usado. Revoga-lo nao altera a organizacao criada - '
                'para isso, mude o plano dela em Organizacoes.',
            )
            return redirect('superadmin:invitations')
        invitation.revoked_at = timezone.now()
        invitation.save(update_fields=['revoked_at', 'updated_at'])
        record_audit_event(
            request.user, None, 'tenancy.platform_invitation_revoked',
            object_type='invitation', object_id=invitation.id, outcome='success',
        )
        messages.success(request, 'Convite revogado.')
        return redirect('superadmin:invitations')


# --------------------------------------------------------------------- leads

class ClinicMessagesView(SuperAdminView):
    """O que as clínicas escreveram: pedidos de ajuda e sugestões.

    Atravessa organizações, como a trilha de auditoria e pela mesma razão:
    quem opera a instalação precisa ver todas. O que ele **não** vê aqui,
    como em todo o console, é prontuário — a tela de quem escreve avisa
    para não colar dado de paciente, e o modelo não tem campo para anexo.

    Só leitura, como o resto. Marcar "respondida" seria uma escrita a mais
    e um estado que ninguém atualiza: quem responde responde do próprio
    e-mail, e a caixa dele é onde o assunto continua.

    `notify_error` aparece na linha porque é o único lugar onde se
    descobre que o aviso não saiu — quem escreveu viu "mensagem enviada",
    e viu certo: ela está aqui.
    """

    def get(self, request):
        from tenancy.models import ClinicMessage, ClinicMessageKind

        tipo = request.GET.get('kind') or ''
        consulta = ClinicMessage.objects.select_related(
            'tenant', 'author__user',
        ).order_by('-created_at')
        if tipo in ClinicMessageKind.values:
            consulta = consulta.filter(kind=tipo)

        context = _nav('clinic-messages')
        context['rows'] = list(consulta[:PAGE_SIZE])
        context['total'] = ClinicMessage.objects.count()
        context['kinds'] = [
            {'value': v, 'label': l, 'selected': v == tipo}
            for v, l in ClinicMessageKind.choices
        ]
        context['kind_atual'] = tipo
        context['sem_aviso'] = ClinicMessage.objects.exclude(notify_error='').count()
        context['novas'] = ClinicMessage.objects.filter(status='new').count()
        return render(request, 'ops/superadmin/clinic_messages.html', context)


class ContractsView(SuperAdminView):
    """Quem aceitou o contrato de adesao, qual versao, e quando vence.

    Tres perguntas que so tem resposta aqui, e cada uma tem um dia em que
    alguem precisa dela:

    - **A clinica tem contrato?** Uma organizacao sem aceite registrado e
      uma clinica usando o sistema sem contrato. A tela mostra essas
      primeiro, porque e o unico item da lista que exige acao.
    - **Ela aceitou o texto que esta no ar?** A versao sozinha nao
      responde: se alguem editar `tenancy/contract.py` sem trocar
      `VERSAO`, todo aceite passado aponta para um texto que ninguem leu.
      Por isso a coluna compara o SHA-256 gravado no aceite com o do texto
      corrente, e diz quando eles divergem.
    - **Quando vence, e ainda cabe arrependimento?** Prazo de contrato nao
      se calcula de cabeca no dia em que o cliente liga pedindo o
      dinheiro de volta.

    So leitura, como o resto do console. Registrar desistencia daqui seria
    escrita, e a desistencia tem consequencia comercial -- ela passa pelo
    `/admin/`, onde ha formulario, confirmacao e registro de quem fez.
    """

    def get(self, request):
        from tenancy import contract
        from tenancy.contracts import sha_do_texto
        from tenancy.models import ContractAcceptance, Tenant
        from tenancy.plans import brl, plan_label

        sha_atual = sha_do_texto()
        agora = timezone.now()

        linhas = []
        consulta = ContractAcceptance.objects.select_related(
            'tenant', 'accepted_by',
        ).order_by('-created_at')
        for aceite in consulta[:PAGE_SIZE]:
            linhas.append({
                'aceite': aceite,
                'clinica': aceite.tenant.trade_name or aceite.tenant.legal_name,
                'plano': plan_label(aceite.plan),
                'valor': brl(aceite.price_annual_cents) if aceite.price_annual_cents else '',
                'texto_confere': aceite.text_sha256 == sha_atual,
                'versao_atual': aceite.version == contract.VERSAO,
                # A copia arquivada e o que a clausula 2.3 exige, e e a
                # unica coisa que devolve o texto de uma versao que saiu
                # do ar. Sem ela, o aceite prova que houve aceite e nao
                # prova do que.
                'tem_copia': bool(aceite.text),
                'arrependimento_aberto': (
                    aceite.withdrawn_at is None and aceite.withdrawal_deadline > agora
                ),
                'vencido': aceite.expires_at <= agora,
            })

        # Clinicas sem aceite. Sao as que nasceram antes de o contrato
        # existir -- e sao exatamente as que precisam aceitar a proxima
        # versao. Listadas por nome, sem acao: regularizar e conversa
        # comercial, nao botao de console.
        #
        # A contagem e inteira e a lista e curta. Numa instalacao com
        # muitas organizacoes antigas, imprimir todos os nomes vira um
        # paragrafo que ninguem le -- e o numero, que e o que importa,
        # fica perdido no meio dele.
        com_aceite = ContractAcceptance.objects.values_list('tenant_id', flat=True)
        pendentes = Tenant.objects.exclude(id__in=com_aceite).order_by('legal_name')
        sem_contrato = list(pendentes[:NOMES_VISIVEIS])
        sem_contrato_total = pendentes.count()

        context = _nav('contracts')
        context['contrato'] = contract
        context['sha_atual'] = sha_atual
        context['rows'] = linhas
        context['total'] = ContractAcceptance.objects.count()
        context['sem_contrato'] = sem_contrato
        context['sem_contrato_total'] = sem_contrato_total
        context['sem_contrato_ocultos'] = max(0, sem_contrato_total - len(sem_contrato))
        # So conta como falha o envio que foi **tentado** e falhou. Um
        # aceite sem `emailed_at` e sem erro nasceu fora do cadastro (um
        # roteiro, um comando de terminal), e nunca teve via para enviar:
        # contar esses como falha de SMTP manda procurar defeito onde nao
        # ha nenhum.
        context['sem_copia'] = ContractAcceptance.objects.exclude(email_error='').count()
        context['divergentes'] = sum(1 for l in linhas if not l['texto_confere'])
        context['sem_copia_arquivada'] = ContractAcceptance.objects.filter(text='').count()
        return render(request, 'ops/superadmin/contracts.html', context)


class LeadsView(SuperAdminView):
    """Pedidos de contato vindos da pagina de vendas.

    So leitura, como quase todo o console. Marcar como contatado ou
    descartado seria uma terceira escrita, e ela nao se justifica ainda:
    quem opera esta instalacao responde os leads pelo proprio e-mail, e um
    estado que ninguem atualiza e pior do que estado nenhum -- a tela
    passaria a mentir.

    `notify_error` aparece na linha de proposito. E o unico lugar onde se
    descobre que o e-mail de aviso nao saiu: quem preencheu o formulario
    viu "recebemos", e viu certo, porque o pedido esta aqui.
    """

    def get(self, request):
        from tenancy.models import Lead
        from tenancy.plans import PLANS

        linhas = []
        for lead in Lead.objects.order_by('-created_at')[:PAGE_SIZE]:
            linhas.append({
                'obj': lead,
                'plan_label': PLANS.get(lead.plan, {}).get('label', '') if lead.plan else '',
            })
        context = _nav('leads')
        context['rows'] = linhas
        context['total'] = Lead.objects.count()
        context['sem_aviso'] = Lead.objects.exclude(notify_error='').count()
        return render(request, 'ops/superadmin/leads.html', context)


def _is_iso_date(value):
    try:
        timezone.datetime.fromisoformat(value)
        return True
    except ValueError:
        return False
