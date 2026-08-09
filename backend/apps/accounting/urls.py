# =============================================================================
# === backend/apps/accounting/urls.py ===
# =============================================================================
from django.urls import path

from .views import (AgingAPView, AgingARView, BalanceSheetView,
                    ProfitLossView, TrialBalanceView)

urlpatterns = [
    path("trial-balance/", TrialBalanceView.as_view(), name="trial-balance"),
    path("profit-loss/",   ProfitLossView.as_view(),   name="profit-loss"),
    path("balance-sheet/", BalanceSheetView.as_view(), name="balance-sheet"),
    path("aging-ar/",      AgingARView.as_view(),      name="aging-ar"),
    path("aging-ap/",      AgingAPView.as_view(),      name="aging-ap"),
]
