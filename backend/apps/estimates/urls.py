# =============================================================================
# === backend/apps/estimates/urls.py ===
# =============================================================================
from django.urls import path

from .views import (EstimateApproveView, EstimateDetailView,
                    EstimateLineItemDetailView, EstimateLineItemListView,
                    EstimateListView, EstimateQuotationPdfView,
                    EstimateRejectView)

urlpatterns = [
    path("vehicles/<uuid:vehicle_id>/estimates/", EstimateListView.as_view(), name="estimate-list"),

    path("estimates/<uuid:pk>/",         EstimateDetailView.as_view(),  name="estimate-detail"),
    path("estimates/<uuid:pk>/approve/", EstimateApproveView.as_view(), name="estimate-approve"),
    path("estimates/<uuid:pk>/reject/",  EstimateRejectView.as_view(),  name="estimate-reject"),
    path("estimates/<uuid:pk>/quotation.pdf", EstimateQuotationPdfView.as_view(), name="estimate-quotation-pdf"),

    path("estimates/<uuid:estimate_id>/line-items/",
         EstimateLineItemListView.as_view(), name="estimate-line-item-list"),
    path("estimates/line-items/<uuid:pk>/",
         EstimateLineItemDetailView.as_view(), name="estimate-line-item-detail"),
]
