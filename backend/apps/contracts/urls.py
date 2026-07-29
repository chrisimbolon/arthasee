# =============================================================================
# === backend/apps/contracts/urls.py ===
# =============================================================================
from django.urls import path

from .views import (ContractDetailView, ContractGenerateTerminView,
                    ContractImportApplyView, ContractImportDetailView,
                    ContractImportRejectView, ContractImportUploadView,
                    ContractListView, TerminPeriodRealizeView)

urlpatterns = [
    path("contracts/",                              ContractListView.as_view(),         name="contract-list"),
    path("contracts/<uuid:pk>/",                     ContractDetailView.as_view(),        name="contract-detail"),
    path("contracts/<uuid:pk>/generate-termin/",     ContractGenerateTerminView.as_view(), name="contract-generate-termin"),
    path("contracts/<uuid:contract_id>/imports/",    ContractImportUploadView.as_view(),  name="contract-import-upload"),
    path("contract-imports/<uuid:pk>/",              ContractImportDetailView.as_view(),  name="contract-import-detail"),
    path("contract-imports/<uuid:pk>/apply/",        ContractImportApplyView.as_view(),   name="contract-import-apply"),
    path("contract-imports/<uuid:pk>/reject/",       ContractImportRejectView.as_view(),  name="contract-import-reject"),
    # Made's own real termin-tracking example (28 Jul meeting) — see
    # TerminPeriod's own docstring in models.py.
    path("termin-periods/<uuid:pk>/realize/",        TerminPeriodRealizeView.as_view(),   name="termin-period-realize"),
]
