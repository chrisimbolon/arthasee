# =============================================================================
# === backend/apps/analytics/urls.py ===
# =============================================================================
from django.urls import path

from .views import (CustomerGrowthTrendView, JobVolumeTrendView,
                    MechanicUtilizationView, RevenueTrendView,
                    WorkOrderQueueStatusView)

urlpatterns = [
    path("revenue-trend/",         RevenueTrendView.as_view(),          name="revenue-trend"),
    path("mechanic-utilization/",  MechanicUtilizationView.as_view(),   name="mechanic-utilization"),
    path("queue-status/",          WorkOrderQueueStatusView.as_view(),  name="queue-status"),
    path("job-volume-trend/",      JobVolumeTrendView.as_view(),        name="job-volume-trend"),
    path("customer-growth-trend/", CustomerGrowthTrendView.as_view(),   name="customer-growth-trend"),
]
