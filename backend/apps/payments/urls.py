# =============================================================================
# === backend/apps/payments/urls.py ===
# =============================================================================
from django.urls import path

from .views import (InvoicePaymentListCreateView, InvoiceRefundView,
                    SupplierInvoicePayView)

urlpatterns = [
    path("invoices/<uuid:invoice_id>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
    path("invoices/<uuid:invoice_id>/refund/",   InvoiceRefundView.as_view(),            name="invoice-refund"),
    path("supplier-invoices/<uuid:supplier_invoice_id>/pay/", SupplierInvoicePayView.as_view(), name="supplier-invoice-pay"),
]
