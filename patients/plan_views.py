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
    return list(
        HealthPlan.objects.filter(tenant_id=tenant_id)
        .select_related('insurer')
        .annotate(coverage_count=Count('coverages', distinct=True))
        .order_by('insurer__name', '-active', 'name')
    )


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
