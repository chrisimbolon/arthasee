# =============================================================================
# === backend/apps/payments/urls.py ===
# =============================================================================
from django.urls import path

from .views import InvoicePaymentListCreateView

urlpatterns = [
    path("invoices/<uuid:invoice_id>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
]
