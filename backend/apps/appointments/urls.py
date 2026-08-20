# =============================================================================
# === backend/apps/appointments/urls.py ===
# =============================================================================
from django.urls import path

from .views import AppointmentAvailabilityView, AppointmentCancelView, AppointmentListCreateView

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
]
