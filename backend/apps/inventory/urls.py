# =============================================================================
# === backend/apps/inventory/urls.py ===
# Identical paths to what previously lived in apps.service.urls — the
# API contract doesn't change just because the Python module backing
# it moved. Frontend's service.ts needs zero changes for this refactor.
# =============================================================================
from django.urls import path

from .views import PartDetailView, PartListView, PartUsageListView, StockAdjustmentListView

urlpatterns = [
    path("parts/",              PartListView.as_view(),   name="part-list"),
    path("parts/<uuid:pk>/",    PartDetailView.as_view(), name="part-detail"),

    path("parts/<uuid:part_id>/adjustments/",
         StockAdjustmentListView.as_view(), name="stock-adjustment-list"),

    path("service-records/<uuid:service_record_id>/part-usages/",
         PartUsageListView.as_view(), name="part-usage-list"),
]
