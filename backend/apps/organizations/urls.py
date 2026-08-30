# =============================================================================
# === backend/apps/organizations/urls.py ===
# =============================================================================
from django.urls import path

from .views import MyOrganizationView, OrganizationOnboardingCompleteView

urlpatterns = [
    path("mine/", MyOrganizationView.as_view(), name="organization-mine"),
    # 29 Aug 2026 — real onboarding gate, Chris's own confirmed design.
    path("mine/complete-onboarding/", OrganizationOnboardingCompleteView.as_view(), name="organization-complete-onboarding"),
]
