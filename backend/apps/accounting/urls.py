# =============================================================================
# === backend/apps/accounting/urls.py ===
# =============================================================================
from django.urls import path

from .views import (AccountDetailView, AccountingPeriodCloseView,
                    AccountingPeriodListView, AccountingPeriodReopenView,
                    AccountListCreateView, AgingAPView, AgingARView,
                    AssetListCreateView, BalanceSheetView,
                    BankStatementLineDetailView,
                    BankStatementLineListCreateView, CashConversionCycleView,
                    DailyCashActivityView, DashboardFinancialSummaryView,
                    DepreciationRunDetailView, FailedPostingsView,
                    GeneralLedgerView, JournalEntryCorrectView,
                    JournalEntryDetailView, JournalEntryListView,
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
                    OpeningBalancePostView, OpeningBalancePreviewView,
                    OpeningBalanceReceivableDetailView,
                    OpeningBalanceReceivableListCreateView,
                    OpeningBalanceSessionView, ProfitLossTrendView,
                    ProfitLossView, ReconciliationMatchDetailView,
                    ReconciliationMatchListCreateView,
                    ReconciliationSummaryView, TrialBalanceView)

urlpatterns = [
    path("trial-balance/",   TrialBalanceView.as_view(),           name="trial-balance"),
    path("profit-loss/",     ProfitLossView.as_view(),             name="profit-loss"),
    path("profit-loss-trend/", ProfitLossTrendView.as_view(),      name="profit-loss-trend"),
    path("balance-sheet/",   BalanceSheetView.as_view(),           name="balance-sheet"),
    path("cash-conversion-cycle/", CashConversionCycleView.as_view(), name="cash-conversion-cycle"),
    path("aging-ar/",        AgingARView.as_view(),                name="aging-ar"),
    path("aging-ap/",        AgingAPView.as_view(),                name="aging-ap"),
    path("dashboard-financial-summary/", DashboardFinancialSummaryView.as_view(), name="dashboard-financial-summary"),
    # 1 Sep 2026 — Kas Harian, Made's own confirmed real request.
    path("daily-cash-activity/", DailyCashActivityView.as_view(), name="daily-cash-activity"),
    # 4 Sep 2026 — General Ledger (Buku Besar), account-centric view.
    path("general-ledger/", GeneralLedgerView.as_view(), name="general-ledger"),
    # 9 Sep 2026 — Phase 17, Task 17.1. The real, previously-missing
    # Chart of Accounts management endpoint — found absent during
    # Phase 17 design review. A hard precondition for Task 17.2
    # (Sub-Accounts) to be usable at all.
    path("accounts/", AccountListCreateView.as_view(), name="account-list-create"),
    path("accounts/<uuid:pk>/", AccountDetailView.as_view(), name="account-detail"),
    # 9 Sep 2026 — Phase 17, Task 17.3. Bank Reconciliation — manual
    # statement entry v1 (Open Decision #20 defers a real live bank-
    # feed integration). Literal paths (statement-lines/, matches/)
    # BEFORE the <str:account_code> catch-all — see this file's own
    # header note for why the order matters here.
    path("reconciliation/statement-lines/", BankStatementLineListCreateView.as_view(), name="reconciliation-statement-line-list-create"),
    path("reconciliation/statement-lines/<uuid:pk>/", BankStatementLineDetailView.as_view(), name="reconciliation-statement-line-detail"),
    path("reconciliation/matches/", ReconciliationMatchListCreateView.as_view(), name="reconciliation-match-list-create"),
    path("reconciliation/matches/<uuid:pk>/", ReconciliationMatchDetailView.as_view(), name="reconciliation-match-detail"),
    path("reconciliation/<str:account_code>/", ReconciliationSummaryView.as_view(), name="reconciliation-summary"),
    path("manual-journals/", ManualJournalListCreateView.as_view(), name="manual-journal-list-create"),
    path("journal-entries/", JournalEntryListView.as_view(),       name="journal-entry-list"),
    path("journal-entries/<uuid:pk>/", JournalEntryDetailView.as_view(), name="journal-entry-detail"),
    path("journal-entries/<uuid:pk>/correct/", JournalEntryCorrectView.as_view(), name="journal-entry-correct"),
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
    # 8 Sep 2026 — the real pre-commit review gate, Chris/Aris's own
    # confirmed hybrid design for the Opening Balance Equity plug:
    # read-only, safe to call any number of times while the session
    # is still DRAFT, placed between session-create and the final,
    # irreversible post — matching the real order a wizard actually
    # walks through (create -> fill in lines -> preview -> post).
    path("opening-balance/preview/",       OpeningBalancePreviewView.as_view(),         name="opening-balance-preview"),
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