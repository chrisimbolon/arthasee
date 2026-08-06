# =============================================================================
# === backend/apps/letters/urls.py ===
# =============================================================================
from django.urls import path

from .views import (IncomingLetterDetailView, IncomingLetterListView,
                    OutgoingLetterDetailView, OutgoingLetterListView)

urlpatterns = [
    path("outgoing/", OutgoingLetterListView.as_view()),
    path("outgoing/<uuid:pk>/", OutgoingLetterDetailView.as_view()),
    path("incoming/", IncomingLetterListView.as_view()),
    path("incoming/<uuid:pk>/", IncomingLetterDetailView.as_view()),
]
