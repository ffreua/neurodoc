"""Cadastro de convênios e planos de saúde, na área administrativa.

Existiam só no admin técnico do Django, que é do responsável pelo servidor
e não do responsável pela clínica. O resultado prático é que quem
administra a clínica não conseguia cadastrar um convênio novo: a ficha do
paciente oferecia uma lista que ninguém dali podia alimentar.

Convênio e plano são dois níveis de propósito. Um convênio ("Bradesco
Saúde") tem vários planos, e o que muda carência, coparticipação e valor é
o plano, não a operadora. Uma tela só, com os dois misturados, obrigaria a
repetir o nome da operadora em cada linha — e a errar a grafia em alguma.

Nada aqui é apagado. Convênio e plano ficam presos por `PROTECT` a
`PatientCoverage` e a `FeeSchedule`: apagar o plano de um paciente que o
usou apagaria o registro de sob qual cobertura ele foi atendido. Sai de
circulação desmarcando "aceito pela clínica" — some das listas de escolha
e continua legível onde já foi usado.
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from audit.services import record_audit_event
from tenancy.permissions import Capability, CapabilityRequiredView

from .models import HealthPlan, Insurer
from .plan_forms import HealthPlanForm, InsurerForm


class HealthPlanAdminView(CapabilityRequiredView):
    required_capability = Capability.MANAGE_HEALTH_PLANS

    @property
    def tenant_id(self):
        return self.request.access_context.tenant_id


def _insurer_rows(tenant_id):
    """Convênios com quantos planos e quantos pacientes dependem deles.

    A contagem de pacientes é o que impede a pergunta "posso desativar
    este?" de ser respondida por adivinhação: um convênio com 300
    coberturas ativas não some da clínica porque alguém arrumou a lista.
    """
    return list(
        Insurer.objects.filter(tenant_id=tenant_id)
        .annotate(
            plan_count=Count('plans', distinct=True),
            active_plan_count=Count('plans', filter=Q(plans__active=True), distinct=True),
            coverage_count=Count('plans__coverages', distinct=True),
        )
        .order_by('-active', 'name')
    )


def _plan_rows(tenant_id):
    """Os planos da clinica, com o que prende cada um.

    `fee_count` entra junto com `coverage_count` porque as duas chaves
    `PROTECT` que impedem apagar um plano sao essas: cobertura de paciente
    e tabela de valores. Contar so a primeira faria o botao de excluir
    aparecer para um plano que a tabela de honorarios prende -- e o erro
    so apareceria depois do clique.

    Uma consulta anotada, e nao duas por linha: a tela lista todos os
    planos da clinica, e uma contagem por plano seria N+1.
    """
    from finance.models import FeeSchedule

    planos = list(
        HealthPlan.objects.filter(tenant_id=tenant_id)
        .select_related('insurer')
        .annotate(coverage_count=Count('coverages', distinct=True))
        .order_by('insurer__name', '-active', 'name')
    )
    # `FeeSchedule.plan` tem `related_name='+'`, ou seja, nao ha relacao
    # reversa: `Count('feeschedule')` levanta `FieldError`. Uma consulta
    # agrupada resolve em uma ida ao banco, em vez de uma contagem por
    # linha -- que seria N+1 numa tela que lista todos os planos.
    por_plano = dict(
        FeeSchedule.objects.filter(tenant_id=tenant_id, plan__isnull=False)
        .values_list('plan_id')
        .annotate(total=Count('id'))
        .values_list('plan_id', 'total')
    )
    for plano in planos:
        plano.fee_count = por_plano.get(plano.id, 0)
    return planos


class HealthPlanListView(HealthPlanAdminView):
    def _context(self, **overrides):
        context = {
            'insurers': _insurer_rows(self.tenant_id),
            'plans': _plan_rows(self.tenant_id),
            'insurer_form': InsurerForm(),
            'plan_form': HealthPlanForm(tenant_id=self.tenant_id),
            'has_insurer': Insurer.objects.filter(tenant_id=self.tenant_id).exists(),
        }
        context.update(overrides)
        return context

    def get(self, request):
        return render(request, 'patients/health_plans.html', self._context())


class InsurerCreateView(HealthPlanAdminView):
    def post(self, request):
        form = InsurerForm(request.POST)
        if form.is_valid():
            duplicate = Insurer.objects.filter(
                tenant_id=self.tenant_id, name__iexact=form.cleaned_data['name'],
            ).exists()
            if duplicate:
                # Dois convênios com o mesmo nome não são recusados pelo
                # banco, e a consequência aparece longe daqui: a recepção
                # escolhe um dos dois na ficha, o financeiro lança no
                # outro, e o relatório mostra a operadora partida em duas.
                form.add_error('name', 'Já existe um convênio com este nome nesta clínica.')
        if not form.is_valid():
            return render(request, 'patients/health_plans.html',
                          HealthPlanListView._context(self, insurer_form=form))
        insurer = form.save(commit=False)
        insurer.tenant_id = self.tenant_id
        insurer.full_clean()
        insurer.save()
        record_audit_event(
            request.user, self.tenant_id, 'patients.insurer_created',
            object_type='insurer', object_id=insurer.id, outcome='success',
        )
        messages.success(
            request,
            f'Convênio "{insurer.name}" cadastrado. Cadastre agora ao menos um plano — '
            'é o plano que o paciente tem, não a operadora.',
        )
        return redirect('health-plans:list')


class InsurerUpdateView(HealthPlanAdminView):
    def post(self, request, insurer_id):
        insurer = get_object_or_404(Insurer, id=insurer_id, tenant_id=self.tenant_id)
        # Lido **antes** de o formulário existir. `is_valid()` chama
        # `_post_clean`, que grava os dados enviados na própria instância:
        # depois dele, `insurer.active` já é o valor novo, e a comparação
        # "estava ativo e deixou de estar" nunca seria verdadeira.
        was_active = insurer.active
        form = InsurerForm(request.POST, instance=insurer)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('health-plans:list')
        saved = form.save(commit=False)
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, self.tenant_id, 'patients.insurer_updated',
            object_type='insurer', object_id=saved.id, outcome='success',
            integrity_metadata={'active': saved.active},
        )
        if was_active and not saved.active:
            # Desativar a operadora sem desativar os planos deixaria os
            # planos dela ainda escolhíveis na ficha — o convênio sairia da
            # lista e continuaria entrando por baixo.
            afetados = HealthPlan.objects.filter(
                tenant_id=self.tenant_id, insurer=saved, active=True,
            ).update(active=False)
            messages.success(
                request,
                f'Convênio "{saved.name}" desativado'
                + (f', junto com {afetados} plano(s) dele.' if afetados else '.'),
            )
        else:
            messages.success(request, f'Convênio "{saved.name}" salvo.')
        return redirect('health-plans:list')


class HealthPlanCreateView(HealthPlanAdminView):
    def post(self, request):
        form = HealthPlanForm(request.POST, tenant_id=self.tenant_id)
        if not form.is_valid():
            return render(request, 'patients/health_plans.html',
                          HealthPlanListView._context(self, plan_form=form))
        plan = form.save(commit=False)
        plan.tenant_id = self.tenant_id
        if HealthPlan.objects.filter(
            tenant_id=self.tenant_id, insurer=plan.insurer, name__iexact=plan.name,
        ).exists():
            form.add_error('name', 'Este convênio já tem um plano com este nome.')
            return render(request, 'patients/health_plans.html',
                          HealthPlanListView._context(self, plan_form=form))
        plan.full_clean()
        plan.save()
        record_audit_event(
            request.user, self.tenant_id, 'patients.health_plan_created',
            object_type='health_plan', object_id=plan.id, outcome='success',
        )
        messages.success(request, f'Plano "{plan.name}" cadastrado em {plan.insurer.name}.')
        return redirect('health-plans:list')


class HealthPlanUpdateView(HealthPlanAdminView):
    def post(self, request, plan_id):
        plan = get_object_or_404(HealthPlan, id=plan_id, tenant_id=self.tenant_id)
        form = HealthPlanForm(request.POST, instance=plan, tenant_id=self.tenant_id)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('health-plans:list')
        saved = form.save(commit=False)
        saved.full_clean()
        saved.save()
        record_audit_event(
            request.user, self.tenant_id, 'patients.health_plan_updated',
            object_type='health_plan', object_id=saved.id, outcome='success',
            integrity_metadata={'active': saved.active},
        )
        messages.success(request, f'Plano "{saved.name}" salvo.')
        return redirect('health-plans:list')


def insurer_usage(insurer):
    """Quem prende este convenio, e por que ele nao pode sumir.

    Uma chave `PROTECT` aponta para `Insurer`: `HealthPlan.insurer`. Logo o
    convenio so pode ser apagado quando nao tem plano nenhum pendurado.

    A contagem de coberturas vai junto **so para a mensagem**: dizer "3
    planos" e menos util que dizer "3 planos, e 12 pacientes atendidos por
    eles", porque e isso que explica por que o caminho nao e apagar e sim
    desmarcar "Aceito pela clinica".

    Devolve `(planos, coberturas)`.
    """
    from .models import PatientCoverage

    planos = insurer.plans.count()
    coberturas = PatientCoverage.objects.filter(plan__insurer=insurer).count()
    return planos, coberturas


def plan_usage(plan):
    """Quem prende este plano, e por que ele nao pode sumir.

    Duas chaves `PROTECT` apontam para `HealthPlan`:
    `PatientCoverage.plan` e `FeeSchedule.plan`. Nao sao um detalhe de
    banco -- sao a regra: apagar um plano usado apagaria o registro de sob
    qual cobertura um paciente foi atendido, e de qual valor foi cobrado.
    Isso e historia clinica e financeira, nao cadastro.

    Devolve `(coberturas, tabelas_de_valor)`. Zero nos dois significa um
    plano que nunca foi usado -- cadastrado com o nome errado, ou duplicado
    --, e esse pode ser apagado sem apagar nada mais.
    """
    from finance.models import FeeSchedule

    from .models import PatientCoverage

    return (
        PatientCoverage.objects.filter(plan=plan).count(),
        FeeSchedule.objects.filter(plan=plan).count(),
    )


class InsurerDeleteView(HealthPlanAdminView):
    """Apaga um convenio **que nao tem plano nenhum**.

    Mesmo caso do plano, um nivel acima: o convenio entrou com o nome
    errado, ou duplicado, e desativar deixaria lixo permanente na lista de
    quem administra a clinica.

    A cadeia e deliberada e se le de baixo para cima: o plano so sai quando
    nenhum paciente e nenhuma tabela de valores o usam; o convenio so sai
    quando nao tem mais plano. Quem quiser mesmo remover um convenio inteiro
    apaga os planos dele primeiro -- e se algum plano recusar, e porque ha
    historia clinica ou financeira presa nele, que e justamente o que nao
    pode desaparecer por arrumacao de cadastro.

    Para o convenio em uso o caminho continua sendo desmarcar "Aceito pela
    clinica": ele some das listas de escolha e continua legivel onde ja foi
    usado.

    A contagem nao substitui o `PROTECT`: ela existe para a mensagem ser
    util. Se um plano nascer entre a contagem e o `delete`, o
    `ProtectedError` e capturado e nada e apagado.
    """

    def post(self, request, insurer_id):
        from django.db.models import ProtectedError

        insurer = get_object_or_404(
            Insurer, id=insurer_id, tenant_id=self.tenant_id,
        )
        rotulo = str(insurer)
        planos, coberturas = insurer_usage(insurer)
        if planos:
            detalhe = f'{planos} plano(s)'
            if coberturas:
                detalhe += f', com {coberturas} paciente(s) atendido(s) por eles,'
            messages.error(
                request,
                f'{rotulo} nao pode ser excluido: {detalhe} dependem dele. Apague os '
                f'planos primeiro, ou desmarque "Aceito pela clinica" para tira-lo de '
                f'circulacao sem perder o historico.',
            )
            return redirect('health-plans:list')

        try:
            insurer.delete()
        except ProtectedError:
            # Corrida: alguem cadastrou um plano neste convenio enquanto
            # esta tela estava aberta.
            messages.error(
                request,
                f'{rotulo} passou a ter plano enquanto esta tela estava aberta e por '
                'isso nao foi excluido. Recarregue para ver a situacao atual.',
            )
            return redirect('health-plans:list')

        record_audit_event(
            request.user, self.tenant_id, 'patients.insurer_deleted',
            object_type='insurer', object_id=insurer_id, outcome='success',
            integrity_metadata={'label': rotulo},
        )
        messages.success(request, f'{rotulo} excluido. Nenhum plano dependia dele.')
        return redirect('health-plans:list')


class HealthPlanDeleteView(HealthPlanAdminView):
    """Apaga um plano **que nunca foi usado**.

    Existe para o caso real de cadastro errado: o nome saiu trocado, ou o
    plano entrou duas vezes, e desativar deixaria lixo permanente na lista
    de quem administra.

    Fora desse caso, apagar e recusado, e a recusa **diz quem prende** --
    "3 pacientes e 1 tabela de valores" -- em vez de um erro generico que
    mandaria a pessoa procurar. A saida para o plano em uso continua sendo
    desmarcar "Aceito pela clinica": ele some das listas de escolha e
    continua legivel onde ja foi usado.

    A verificacao por contagem nao substitui o `PROTECT`: ela existe para a
    mensagem ser util. O banco continua sendo quem garante -- se uma
    cobertura for criada entre a contagem e o `delete`, o `ProtectedError`
    e capturado e a operacao falha sem apagar nada.
    """

    def post(self, request, plan_id):
        from django.db.models import ProtectedError

        plan = get_object_or_404(
            HealthPlan, id=plan_id, tenant_id=self.tenant_id,
        )
        rotulo = str(plan)
        coberturas, tabelas = plan_usage(plan)
        if coberturas or tabelas:
            partes = []
            if coberturas:
                partes.append(f'{coberturas} paciente(s)')
            if tabelas:
                partes.append(f'{tabelas} tabela(s) de valores')
            messages.error(
                request,
                f'{rotulo} nao pode ser excluido: {" e ".join(partes)} usam este plano, '
                'e apagar apagaria o registro de sob qual cobertura o paciente foi '
                'atendido. Para tira-lo de circulacao, desmarque "Aceito pela clinica".',
            )
            return redirect('health-plans:list')

        try:
            plan.delete()
        except ProtectedError:
            # Corrida: alguem vinculou o plano entre a contagem e o delete.
            messages.error(
                request,
                f'{rotulo} passou a ser usado enquanto esta tela estava aberta '
                'e por isso nao foi excluido. Recarregue para ver a situacao atual.',
            )
            return redirect('health-plans:list')

        record_audit_event(
            request.user, self.tenant_id, 'patients.health_plan_deleted',
            object_type='health_plan', object_id=plan_id, outcome='success',
            integrity_metadata={'label': rotulo},
        )
        messages.success(request, f'{rotulo} excluido. Nenhum paciente usava este plano.')
        return redirect('health-plans:list')
