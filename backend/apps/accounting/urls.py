# =============================================================================
# === backend/apps/accounting/urls.py ===
# =============================================================================
from django.urls import path

from .views import (AgingAPView, AgingARView, BalanceSheetView,
                    FailedPostingsView, JournalEntryListView,
                    ManualJournalListCreateView, ProfitLossView,
                    TrialBalanceView)

urlpatterns = [
    path("trial-balance/",   TrialBalanceView.as_view(),           name="trial-balance"),
    path("profit-loss/",     ProfitLossView.as_view(),             name="profit-loss"),
    path("balance-sheet/",   BalanceSheetView.as_view(),           name="balance-sheet"),
    path("aging-ar/",        AgingARView.as_view(),                name="aging-ar"),
    path("aging-ap/",        AgingAPView.as_view(),                name="aging-ap"),
    path("manual-journals/", ManualJournalListCreateView.as_view(), name="manual-journal-list-create"),
    path("journal-entries/", JournalEntryListView.as_view(),       name="journal-entry-list"),
    path("failed-postings/", FailedPostingsView.as_view(),         name="failed-postings-list"),
]
