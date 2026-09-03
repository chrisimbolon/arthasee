# =============================================================================
# === backend/apps/accounting/urls.py ===
# =============================================================================
from django.urls import path

from .views import (AccountingPeriodCloseView, AccountingPeriodListView,
                    AccountingPeriodReopenView, AgingAPView, AgingARView,
                    AssetListCreateView, BalanceSheetView,
                    CashConversionCycleView, DailyCashActivityView,
                    DashboardFinancialSummaryView, DepreciationRunDetailView,
                    FailedPostingsView, JournalEntryListView,
                    ManualJournalListCreateView,
                    OpeningBalanceAssetLineDetailView,
                    OpeningBalanceAssetLineListCreateView,
                    OpeningBalanceCashLineView,
                    OpeningBalanceOtherLineDetailView,
                    OpeningBalanceOtherLineListCreateView,
                    OpeningBalancePartLineDetailView,
                    OpeningBalancePartLineListCreateView,
                    OpeningBalancePayableDetailView,
                    OpeningBalancePayableListCreateView,
                    OpeningBalancePostView, OpeningBalanceReceivableDetailView,
                    OpeningBalanceReceivableListCreateView,
                    OpeningBalanceSessionView, ProfitLossView,
                    TrialBalanceView)

urlpatterns = [
    path("trial-balance/",   TrialBalanceView.as_view(),           name="trial-balance"),
    path("profit-loss/",     ProfitLossView.as_view(),             name="profit-loss"),
    path("balance-sheet/",   BalanceSheetView.as_view(),           name="balance-sheet"),
    path("cash-conversion-cycle/", CashConversionCycleView.as_view(), name="cash-conversion-cycle"),
    path("aging-ar/",        AgingARView.as_view(),                name="aging-ar"),
    path("aging-ap/",        AgingAPView.as_view(),                name="aging-ap"),
    path("dashboard-financial-summary/", DashboardFinancialSummaryView.as_view(), name="dashboard-financial-summary"),
    # 1 Sep 2026 — Kas Harian, Made's own confirmed real request.
    path("daily-cash-activity/", DailyCashActivityView.as_view(), name="daily-cash-activity"),
    path("manual-journals/", ManualJournalListCreateView.as_view(), name="manual-journal-list-create"),
    path("journal-entries/", JournalEntryListView.as_view(),       name="journal-entry-list"),
    path("failed-postings/", FailedPostingsView.as_view(),         name="failed-postings-list"),
    # 28 Aug 2026 — real month-end period control (Made's own
    # confirmed requirement, via his tax & accounting consultant).
    path("periods/",                    AccountingPeriodListView.as_view(),   name="accounting-period-list"),
    path("periods/<uuid:pk>/close/",    AccountingPeriodCloseView.as_view(),  name="accounting-period-close"),
    path("periods/<uuid:pk>/reopen/",   AccountingPeriodReopenView.as_view(), name="accounting-period-reopen"),
    # 29 Aug 2026 — real fixed asset register & automated
    # depreciation, Made's own confirmed request.
    path("assets/", AssetListCreateView.as_view(), name="asset-list-create"),
    path("periods/<uuid:period_id>/depreciation-run/", DepreciationRunDetailView.as_view(), name="depreciation-run-detail"),
    # 3 Sep 2026 — Opening Balance onboarding, Sansan's own canonical
    # onboarding proposal (meticulously reviewed and revised before
    # any of this was built — see models.py's own module docstring).
    # Session create/read/post are owner-only, real-model-owns-the-
    # logic thin views, same discipline as the period-close endpoints
    # above; the six line-item endpoints underneath are open to any
    # authenticated org member — see views.py's own module docstring
    # for why data entry and the final post carry different stakes.
    path("opening-balance/",               OpeningBalanceSessionView.as_view(),         name="opening-balance-session"),
    path("opening-balance/post/",          OpeningBalancePostView.as_view(),            name="opening-balance-post"),
    path("opening-balance/cash/",          OpeningBalanceCashLineView.as_view(),        name="opening-balance-cash"),
    path("opening-balance/parts/",         OpeningBalancePartLineListCreateView.as_view(), name="opening-balance-part-list-create"),
    path("opening-balance/parts/<uuid:pk>/", OpeningBalancePartLineDetailView.as_view(), name="opening-balance-part-detail"),
    path("opening-balance/assets/",        OpeningBalanceAssetLineListCreateView.as_view(), name="opening-balance-asset-list-create"),
    path("opening-balance/assets/<uuid:pk>/", OpeningBalanceAssetLineDetailView.as_view(), name="opening-balance-asset-detail"),
    path("opening-balance/receivables/",   OpeningBalanceReceivableListCreateView.as_view(), name="opening-balance-receivable-list-create"),
    path("opening-balance/receivables/<uuid:pk>/", OpeningBalanceReceivableDetailView.as_view(), name="opening-balance-receivable-detail"),
    path("opening-balance/payables/",      OpeningBalancePayableListCreateView.as_view(), name="opening-balance-payable-list-create"),
    path("opening-balance/payables/<uuid:pk>/", OpeningBalancePayableDetailView.as_view(), name="opening-balance-payable-detail"),
    path("opening-balance/other/",         OpeningBalanceOtherLineListCreateView.as_view(), name="opening-balance-other-list-create"),
    path("opening-balance/other/<uuid:pk>/", OpeningBalanceOtherLineDetailView.as_view(), name="opening-balance-other-detail"),
]
