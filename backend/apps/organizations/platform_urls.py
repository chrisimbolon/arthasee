# =============================================================================
# === backend/apps/organizations/platform_urls.py ===
# =============================================================================
from django.urls import path

from .platform_views import PlatformOverviewView

urlpatterns = [
    # Phase 22 (24 Oct 2026) — super admin only, read-only.
    path("overview/", PlatformOverviewView.as_view(), name="platform-overview"),
]
