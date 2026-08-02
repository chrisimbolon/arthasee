# =============================================================================
# === backend/apps/customers/urls.py ===
# =============================================================================
from django.urls import path

from .views import PublicTrackingView, TrackingLinkListView, TrackingLinkRevokeView

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
]
