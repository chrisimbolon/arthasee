# =============================================================================
# === backend/apps/workorders/urls.py ===
# =============================================================================
from django.urls import path

from .views import (DashboardSummaryView, MechanicDetailView, MechanicListView,
                    WorkOrderCancelView, WorkOrderCloseView,
                    WorkOrderDetailView, WorkOrderJobLineAssignStageView,
                    WorkOrderJobLineListView, WorkOrderJobLineToggleView,
                    WorkOrderListView, WorkOrderMaterialLineDetailView,
                    WorkOrderMaterialLineListView, WorkOrderStageCompleteView,
                    WorkOrderStageDetailView, WorkOrderStageListView,
                    WorkOrderStageStartView, WorkOrderStatusUpdateView)

urlpatterns = [
    path("vehicles/<uuid:vehicle_id>/work-orders/", WorkOrderListView.as_view(), name="work-order-list"),

    path("work-orders/<uuid:pk>/",         WorkOrderDetailView.as_view(),       name="work-order-detail"),
    path("work-orders/<uuid:pk>/status/",  WorkOrderStatusUpdateView.as_view(), name="work-order-status"),
    path("work-orders/<uuid:pk>/close/",   WorkOrderCloseView.as_view(),        name="work-order-close"),
    path("work-orders/<uuid:pk>/cancel/",  WorkOrderCancelView.as_view(),       name="work-order-cancel"),

    path("work-orders/<uuid:work_order_id>/job-lines/",
         WorkOrderJobLineListView.as_view(), name="work-order-job-line-list"),
    path("work-orders/job-lines/<uuid:pk>/toggle/",
         WorkOrderJobLineToggleView.as_view(), name="work-order-job-line-toggle"),
    path("work-orders/job-lines/<uuid:pk>/assign-stage/",
         WorkOrderJobLineAssignStageView.as_view(), name="work-order-job-line-assign-stage"),

    path("work-orders/<uuid:work_order_id>/material-lines/",
         WorkOrderMaterialLineListView.as_view(), name="work-order-material-line-list"),
    path("work-orders/material-lines/<uuid:pk>/",
         WorkOrderMaterialLineDetailView.as_view(), name="work-order-material-line-detail"),

    # Made's own request — custom, per-repair stage tracking. See
    # WorkOrderStage's own docstring in models.py for why this is a
    # separate, additive concept from WorkOrder.status.
    path("work-orders/<uuid:work_order_id>/stages/",
         WorkOrderStageListView.as_view(), name="work-order-stage-list"),
    path("work-orders/stages/<uuid:pk>/",
         WorkOrderStageDetailView.as_view(), name="work-order-stage-detail"),
    path("work-orders/stages/<uuid:pk>/start/",
         WorkOrderStageStartView.as_view(), name="work-order-stage-start"),
    path("work-orders/stages/<uuid:pk>/complete/",
         WorkOrderStageCompleteView.as_view(), name="work-order-stage-complete"),

    # Made's own 28 Jul Owner Dashboard requirements — Mechanic is a
    # lightweight roster (mechanics never log in, unchanged), and
    # dashboard/summary/ aggregates across Mechanic/WorkOrder/
    # WorkOrderStage in one call for a single dashboard screen.
    path("mechanics/", MechanicListView.as_view(), name="mechanic-list"),
    path("mechanics/<uuid:pk>/", MechanicDetailView.as_view(), name="mechanic-detail"),
    path("dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
]
