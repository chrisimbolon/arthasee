# =============================================================================
# === backend/apps/payments/urls.py ===
# =============================================================================
from django.urls import path

from .views import InvoicePaymentListCreateView, InvoiceRefundView

urlpatterns = [
    path("invoices/<uuid:invoice_id>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
    path("invoices/<uuid:invoice_id>/refund/",   InvoiceRefundView.as_view(),            name="invoice-refund"),
]
