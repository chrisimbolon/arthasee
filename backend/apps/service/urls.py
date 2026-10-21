# =============================================================================
# === backend/apps/service/urls.py ===
# =============================================================================
from django.urls import path

from .views import (CustomerDetailView, CustomerHistoryView, CustomerListView,
                    ServiceItemDetailView, ServiceItemHistoryView,
                    ServiceItemListView, ServiceRecordListView,
                    VehicleDetailView, VehicleHistoryView, VehicleListView)

urlpatterns = [
    path("customers/",            CustomerListView.as_view(),   name="customer-list"),
    path("customers/<uuid:pk>/",  CustomerDetailView.as_view(), name="customer-detail"),

    path("customers/<uuid:pk>/history/", CustomerHistoryView.as_view(), name="customer-history"),
    path("vehicles/",             VehicleListView.as_view(),    name="vehicle-list"),
    path("vehicles/<uuid:pk>/",   VehicleDetailView.as_view(),  name="vehicle-detail"),
    path("vehicles/<uuid:pk>/history/", VehicleHistoryView.as_view(), name="vehicle-history"),

    path("vehicles/<uuid:vehicle_id>/service-records/",
         ServiceRecordListView.as_view(), name="service-record-list"),

    # 20 Oct 2026 (Phase 21, Task 21.3) — Daftar Jasa.
    path("service-items/",                    ServiceItemListView.as_view(),    name="service-item-list"),
    path("service-items/<uuid:pk>/",          ServiceItemDetailView.as_view(),  name="service-item-detail"),
    path("service-items/<uuid:pk>/history/",  ServiceItemHistoryView.as_view(), name="service-item-history"),
]
