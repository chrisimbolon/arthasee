# =============================================================================
# === backend/apps/service/urls.py ===
# =============================================================================
from django.urls import path

from .views import (CustomerDetailView, CustomerListView, PartDetailView,
                    PartListView, PartUsageListView, ServiceRecordListView,
                    StockAdjustmentListView, VehicleDetailView,
                    VehicleListView)

urlpatterns = [
    path("customers/",            CustomerListView.as_view(),   name="customer-list"),
    path("customers/<uuid:pk>/",  CustomerDetailView.as_view(), name="customer-detail"),

    path("vehicles/",             VehicleListView.as_view(),    name="vehicle-list"),
    path("vehicles/<uuid:pk>/",   VehicleDetailView.as_view(),  name="vehicle-detail"),

    path("vehicles/<uuid:vehicle_id>/service-records/",
         ServiceRecordListView.as_view(), name="service-record-list"),

    # ── Sprint 1: Inventory ──────────────────────────────────────
    path("parts/",              PartListView.as_view(),   name="part-list"),
    path("parts/<uuid:pk>/",    PartDetailView.as_view(), name="part-detail"),

    path("parts/<uuid:part_id>/adjustments/",
         StockAdjustmentListView.as_view(), name="stock-adjustment-list"),

    path("service-records/<uuid:service_record_id>/part-usages/",
         PartUsageListView.as_view(), name="part-usage-list"),
]
