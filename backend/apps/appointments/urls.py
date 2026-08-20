# =============================================================================
# === backend/apps/appointments/urls.py ===
# =============================================================================
from django.urls import path

from .views import (AppointmentAvailabilityView, AppointmentCancelView,
                    AppointmentListCreateView, TenantAppointmentCancelView,
                    TenantAppointmentConvertView, TenantAppointmentListView)

urlpatterns = [
    # Literal route before the <uuid:pk> one below, matching this
    # project's established convention — though "availability" can't
    # actually match the uuid converter anyway, so this is defensive
    # ordering, not a fix for a real collision.
    path("customer/appointments/availability/",
         AppointmentAvailabilityView.as_view(), name="appointment-availability"),
    path("customer/appointments/",
         AppointmentListCreateView.as_view(), name="appointment-list-create"),
    path("customer/appointments/<uuid:pk>/cancel/",
         AppointmentCancelView.as_view(), name="appointment-cancel"),

    # Staff-facing — no /customer/ prefix, genuinely distinct paths
    # from the customer routes above, no collision.
    path("appointments/",
         TenantAppointmentListView.as_view(), name="tenant-appointment-list"),
    path("appointments/<uuid:pk>/convert/",
         TenantAppointmentConvertView.as_view(), name="tenant-appointment-convert"),
    path("appointments/<uuid:pk>/cancel/",
         TenantAppointmentCancelView.as_view(), name="tenant-appointment-cancel"),
]
