from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import Notification
from .services import mark_read


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


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
