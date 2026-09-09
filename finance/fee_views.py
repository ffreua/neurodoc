"""Tabela de honorários: quanto custa a consulta e o procedimento.

O motor de preço já existia — `finance.pricing.resolve_price` escolhe a
regra mais específica que se aplica na data, e `create_fee_schedule`
recusa duas regras equivalentes com vigência sobreposta. O que faltava era
a tela. Sem ela, definir o valor de uma consulta exigia o admin técnico do
Django, que é de quem opera o servidor e não de quem administra a clínica.

Quem mexe em quê está em `tenancy.permissions.can_set_fee_for`: dono e
gestor definem qualquer valor, inclusive a regra geral da clínica; o
médico define o dele. Um médico que altera o valor do colega muda o que a
clínica fatura por um atendimento que não é dele.

Nada é apagado. Uma regra sai de vigor recebendo data final — o
recebimento já emitido guarda um retrato do que valia (`fee_snapshot`), e
a regra é o que explica de onde aquele retrato veio.
"""

from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from audit.services import record_audit_event
from tenancy.models import Role
from tenancy.permissions import Capability, CapabilityRequiredView, can_set_fee_for

from .fee_forms import FeeScheduleCloseForm, FeeScheduleForm
from .models import FeeSchedule
from .pricing import OverlappingFeeSchedule, create_fee_schedule


class FeeAdminView(CapabilityRequiredView):
    required_capability = Capability.MANAGE_FEES

    @property
    def tenant_id(self):
        return self.request.access_context.tenant_id


def _rows(tenant_id, context):
    """As regras da clínica, com a vigência resolvida para a tela.

    `is_current` é calculado aqui e não no template: uma regra pode estar
    cadastrada e ainda não valer (começa mês que vem) ou já ter vencido, e
    as três situações precisam ser distinguíveis de relance — uma tabela
    que mostra tudo igual faz alguém cadastrar de novo o que já existe.
    """
    hoje = date.today()
    regras = (
        FeeSchedule.objects.filter(tenant_id=tenant_id)
        .select_related('physician__user', 'plan__insurer', 'procedure')
        .order_by('physician__user__first_name', 'payment_category', '-effective_from')
    )
    linhas = []
    for regra in regras:
        vigente = regra.effective_from <= hoje and (
            regra.effective_to is None or regra.effective_to >= hoje
        )
        futura = regra.effective_from > hoje
        linhas.append({
            'obj': regra,
            'is_current': vigente,
            'is_future': futura,
            'is_past': not vigente and not futura,
            'can_edit': can_set_fee_for(context, regra.physician_id),
        })
    return linhas


class FeeScheduleListView(FeeAdminView):
    def _context(self, **overrides):
        context = self.request.access_context
        roles = set(context.permissions)
        administrative = bool({Role.OWNER, Role.MANAGER} & roles)
        data = {
            'rows': _rows(self.tenant_id, context),
            'form': FeeScheduleForm(tenant_id=self.tenant_id, context=context),
            'close_form': FeeScheduleCloseForm(),
            'is_administrative': administrative,
        }
        data.update(overrides)
        return data

    def get(self, request):
        return render(request, 'finance/fees.html', self._context())


class FeeScheduleCreateView(FeeAdminView):
    def post(self, request):
        context = request.access_context
        form = FeeScheduleForm(request.POST, tenant_id=self.tenant_id, context=context)
        if not form.is_valid():
            return render(request, 'finance/fees.html',
                          FeeScheduleListView._context(self, form=form))

        from tenancy.models import Tenant

        try:
            regra = create_fee_schedule(
                Tenant.objects.get(id=self.tenant_id),
                payment_category=form.cleaned_data['payment_category'],
                gross_amount=form.cleaned_data['gross_amount'],
                doctor_share_amount=form.cleaned_data['doctor_share_amount'],
                effective_from=form.cleaned_data['effective_from'],
                effective_to=form.cleaned_data['effective_to'],
                physician=form.physician_object(),
                plan=form.plan_object(),
                procedure=form.procedure_object(),
            )
        except OverlappingFeeSchedule:
            # Duas regras iguais valendo ao mesmo tempo tornam o preço
            # indeterminado: qual das duas responde depende da ordem em que
            # o banco as devolve. A saída é encerrar a anterior.
            form.add_error(
                'effective_from',
                'Já existe uma regra igual a esta valendo neste período. Encerre a anterior '
                'antes — na lista, em "Encerrar" —, ou comece esta no dia seguinte ao fim dela.',
            )
            return render(request, 'finance/fees.html',
                          FeeScheduleListView._context(self, form=form))

        record_audit_event(
            request.user, self.tenant_id, 'finance.fee_schedule_created',
            object_type='fee_schedule', object_id=regra.id, outcome='success',
            integrity_metadata={
                'payment_category': regra.payment_category,
                'gross_amount': str(regra.gross_amount),
                'physician': str(regra.physician_id) if regra.physician_id else None,
            },
        )
        messages.success(
            request,
            f'Valor cadastrado, valendo a partir de '
            f'{regra.effective_from.strftime("%d/%m/%Y")}.',
        )
        return redirect('fees:list')


class FeeScheduleCloseView(FeeAdminView):
    """Encerra a vigência de uma regra."""

    def post(self, request, fee_id):
        regra = get_object_or_404(FeeSchedule, id=fee_id, tenant_id=self.tenant_id)
        if not can_set_fee_for(request.access_context, regra.physician_id):
            messages.error(request, 'Você só encerra regra de valor que seja sua.')
            return redirect('fees:list')
        form = FeeScheduleCloseForm(request.POST)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('fees:list')
        fim = form.cleaned_data['effective_to']
        if fim < regra.effective_from:
            messages.error(
                request,
                'A data de encerramento é anterior ao início da vigência. Uma regra que '
                'termina antes de começar nunca se aplica a nada.',
            )
            return redirect('fees:list')
        anterior = regra.effective_to
        regra.effective_to = fim
        regra.row_version += 1
        regra.save(update_fields=['effective_to', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, self.tenant_id, 'finance.fee_schedule_closed',
            object_type='fee_schedule', object_id=regra.id, outcome='success',
            integrity_metadata={'from': str(anterior) if anterior else None, 'to': str(fim)},
        )
        messages.success(
            request, f'Valor encerrado em {fim.strftime("%d/%m/%Y")}.',
        )
        return redirect('fees:list')

