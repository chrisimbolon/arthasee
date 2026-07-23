# =============================================================================
# === backend/apps/workorders/urls.py ===
# =============================================================================
from django.urls import path

from .views import (
    WorkOrderCancelView, WorkOrderCloseView, WorkOrderDetailView, WorkOrderJobLineListView,
    WorkOrderJobLineToggleView, WorkOrderListView, WorkOrderMaterialLineDetailView,
    WorkOrderMaterialLineListView, WorkOrderStatusUpdateView,
)

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

    path("work-orders/<uuid:work_order_id>/material-lines/",
         WorkOrderMaterialLineListView.as_view(), name="work-order-material-line-list"),
    path("work-orders/material-lines/<uuid:pk>/",
         WorkOrderMaterialLineDetailView.as_view(), name="work-order-material-line-detail"),
]
