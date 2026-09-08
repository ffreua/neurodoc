from django.shortcuts import get_object_or_404, redirect, render

from tenancy.permissions import Capability, CapabilityRequiredView
from .models import Notification
from .services import mark_read


class TenantScopedView(CapabilityRequiredView):
    """Notificações do próprio usuário — qualquer vínculo ativo tem as suas.

    `required_capability = None` é decisão, não esquecimento: a consulta já
    é filtrada por `user=request.user`, e o que a caixa mostra é o que o
    sistema mandou para aquela pessoa. Exigir capacidade aqui esconderia do
    médico o aviso de que a IA terminou, e da secretária o de que uma
    entrega falhou.
    """

    required_capability = None


class NotificationListView(TenantScopedView):
    def get(self, request):
        notifications = Notification.objects.filter(
            tenant_id=request.access_context.tenant_id, user=request.user,
        ).order_by('-created_at')
        return render(request, 'notifications/list.html', {'notifications': notifications})


class NotificationMarkReadView(TenantScopedView):
    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification, id=notification_id, tenant_id=request.access_context.tenant_id, user=request.user,
        )
        mark_read(notification)
        return redirect('notifications:list')
