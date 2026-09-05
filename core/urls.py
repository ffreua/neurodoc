from django.contrib import admin
from django.urls import include, path

from ops.docs import technical_docs

urlpatterns = [
    path('admin/dj-control-room-base/', include('dj_control_room_base.urls')),
    path('admin/dj-celery-panel/', include('dj_celery_panel.urls')),
    path('admin/dj-control-room/', include('dj_control_room.urls')),
    path('admin/', admin.site.urls),
    path('technical-docs/', technical_docs, name='technical-docs-index'),
    path('technical-docs/<path:path>', technical_docs, name='technical-docs'),
    path('accounts/', include('accounts.urls')),
]
