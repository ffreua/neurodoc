from django.urls import path

from . import capture_views

app_name = 'capture'

# Public (token-authenticated, not Django-session-authenticated) endpoints
# the capture agent calls directly -- mounted outside /app/ in
# core/urls.py, the same pattern as communications' opaque document links.
urlpatterns = [
    path('upload/<str:session_token>/', capture_views.BatchUploadView.as_view(), name='upload'),
    path('status/<str:session_token>/', capture_views.SessionStatusView.as_view(), name='status'),
]
