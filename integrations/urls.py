from django.urls import path

from . import capture_views

app_name = 'integrations'

# Staff-facing views only -- these require an authenticated tenant session
# (mounted under /app/, per core/urls.py) and are not reachable by the
# capture device itself.
urlpatterns = [
    path('capture/devices/', capture_views.DeviceListView.as_view(), name='capture-devices'),
    path('capture/devices/pair/', capture_views.DevicePairingStartView.as_view(), name='capture-device-pair'),
    path('capture/devices/<uuid:device_id>/revoke/', capture_views.DeviceRevokeView.as_view(), name='capture-device-revoke'),
    path('capture/devices/<uuid:device_id>/sessions/', capture_views.SessionOpenView.as_view(), name='capture-session-open'),
]
