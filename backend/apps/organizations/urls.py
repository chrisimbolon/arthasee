# =============================================================================
# === backend/apps/organizations/urls.py ===
# =============================================================================
from django.urls import path

from .views import (MyOrganizationView, OrganizationLogoView,
                    OrganizationOnboardingCompleteView)

urlpatterns = [
    path("mine/", MyOrganizationView.as_view(), name="organization-mine"),
    # 6 Oct 2026 — logo upload/removal, a real file endpoint separate
    # from MyOrganizationView's own JSON PATCH.
    path("mine/logo/", OrganizationLogoView.as_view(), name="organization-logo"),
    # 29 Aug 2026 — real onboarding gate, Chris's own confirmed design.
    path("mine/complete-onboarding/", OrganizationOnboardingCompleteView.as_view(), name="organization-complete-onboarding"),
]
