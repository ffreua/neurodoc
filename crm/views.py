from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from tenancy.selectors import scope_to_tenant

from .models import CRMCard, CRMStage
from .services import InvalidTransition, move_card


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class CRMBoardView(TenantScopedView):
    """Grid/kanban: administrative fields only (patient name, stage,
    responsible, due date, summary) -- never a diagnosis, hypothesis or any
    other clinical text. Moving a card is a plain <button> per target
    stage, reachable and activatable purely by keyboard (Tab + Enter/Space),
    no drag-and-drop required.
    """

    def get(self, request):
        stages = CRMStage.objects.filter(tenant_id=request.access_context.tenant_id, active=True)
        cards = scope_to_tenant(CRMCard.objects.select_related('patient', 'stage', 'assigned_membership'),
                                 request.access_context)

        stage_filter = request.GET.get('stage')
        if stage_filter:
            cards = cards.filter(stage_id=stage_filter)
        assigned_filter = request.GET.get('assigned')
        if assigned_filter:
            cards = cards.filter(assigned_membership_id=assigned_filter)

        cards = cards.order_by('due_at', '-created_at')
        return render(request, 'crm/board.html', {'stages': stages, 'cards': cards})


class CRMCardMoveView(TenantScopedView):
    def post(self, request, card_id):
        card = get_object_or_404(
            scope_to_tenant(CRMCard.objects.all(), request.access_context), id=card_id,
        )
        to_stage = get_object_or_404(
            scope_to_tenant(CRMStage.objects.all(), request.access_context), id=request.POST.get('to_stage'),
        )
        from tenancy.models import Membership

        actor_membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            move_card(card, to_stage, actor_membership, reason=request.POST.get('reason', ''))
        except InvalidTransition as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('crm:board')
