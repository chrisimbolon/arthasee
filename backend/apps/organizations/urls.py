# =============================================================================
# === backend/apps/organizations/urls.py ===
# =============================================================================
from django.urls import path

from .views import MyOrganizationView

urlpatterns = [
    path("mine/", MyOrganizationView.as_view(), name="organization-mine"),
]
