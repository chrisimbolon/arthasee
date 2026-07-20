# =============================================================================
# === backend/apps/service/urls.py ===
# =============================================================================
from django.urls import path

from .views import CustomerDetailView, CustomerListView, ServiceRecordListView, VehicleDetailView, VehicleListView

urlpatterns = [
    path("customers/",            CustomerListView.as_view(),   name="customer-list"),
    path("customers/<uuid:pk>/",  CustomerDetailView.as_view(), name="customer-detail"),

    path("vehicles/",             VehicleListView.as_view(),    name="vehicle-list"),
    path("vehicles/<uuid:pk>/",   VehicleDetailView.as_view(),  name="vehicle-detail"),

    path("vehicles/<uuid:vehicle_id>/service-records/",
         ServiceRecordListView.as_view(), name="service-record-list"),
]
