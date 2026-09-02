# =============================================================================
# === backend/apps/payments/urls.py ===
# =============================================================================
from django.urls import path

from .views import (InternalCashMutationListCreateView,
                    InvoicePaymentListCreateView, InvoiceRefundView,
                    OperatingExpenseListCreateView, SupplierInvoicePayView)

urlpatterns = [
    path("invoices/<uuid:invoice_id>/payments/", InvoicePaymentListCreateView.as_view(), name="invoice-payments"),
    path("invoices/<uuid:invoice_id>/refund/",   InvoiceRefundView.as_view(),            name="invoice-refund"),
    path("supplier-invoices/<uuid:supplier_invoice_id>/pay/", SupplierInvoicePayView.as_view(), name="supplier-invoice-pay"),
    # 27 Aug 2026 — Made's own confirmed real request.
    path("operating-expenses/", OperatingExpenseListCreateView.as_view(), name="operating-expense-list-create"),
    # 1 Sep 2026 — Made's own confirmed real request, arrived at
    # while designing the Kas Harian dashboard.
    path("internal-cash-mutations/", InternalCashMutationListCreateView.as_view(), name="internal-cash-mutation-list-create"),
]
