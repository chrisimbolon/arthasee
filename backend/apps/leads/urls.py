# =============================================================================
# === backend/apps/leads/urls.py ===
# =============================================================================
from django.urls import path

from .views import RejectedQuoteDetailView, RejectedQuoteListView

urlpatterns = [
    path("leads/rejected-quotes/",           RejectedQuoteListView.as_view(),   name="rejected-quote-list"),
    path("leads/rejected-quotes/<uuid:pk>/", RejectedQuoteDetailView.as_view(), name="rejected-quote-detail"),
]
