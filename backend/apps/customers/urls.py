# =============================================================================
# === backend/apps/customers/urls.py ===
# =============================================================================
from django.urls import path

from .views import (CustomerMagicLinkRequestView, CustomerMagicLinkVerifyView,
                    CustomerSelfRegistrationView, CustomerWorkOrderDetailView,
                    CustomerWorkOrdersListView, PublicTrackingView,
                    TrackingLinkListView, TrackingLinkRevokeView)

urlpatterns = [
    path("work-orders/<uuid:work_order_id>/tracking-links/",
         TrackingLinkListView.as_view(), name="tracking-link-list"),
    path("tracking-links/<uuid:pk>/revoke/",
         TrackingLinkRevokeView.as_view(), name="tracking-link-revoke"),
    # The one deliberately public, unauthenticated route in this
    # entire API — see PublicTrackingView's own docstring for why
    # AllowAny is safe here specifically. token is a str, not a uuid
    # converter — it's a random secrets.token_urlsafe() string, not
    # a UUID.
    path("track/<str:token>/", PublicTrackingView.as_view(), name="public-tracking"),

    # Fase 2.5 — real customer accounts, magic-link login.
    path("customer-auth/magic-link/",
         CustomerMagicLinkRequestView.as_view(), name="customer-magic-link-request"),
    path("customer-auth/magic-link/verify/",
         CustomerMagicLinkVerifyView.as_view(), name="customer-magic-link-verify"),
    # New — self-registration, the missing path for a genuine
    # first-time visitor (see CustomerSelfRegistrationView's own
    # docstring). Grouped right next to the login route it feeds
    # into, not off with the appointment-booking work yet to come.
    path("customer-auth/register/",
         CustomerSelfRegistrationView.as_view(), name="customer-register"),
    path("customer/work-orders/",
         CustomerWorkOrdersListView.as_view(), name="customer-work-order-list"),
    path("customer/work-orders/<uuid:pk>/",
         CustomerWorkOrderDetailView.as_view(), name="customer-work-order-detail"),
]
