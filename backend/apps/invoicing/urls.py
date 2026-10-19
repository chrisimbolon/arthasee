# =============================================================================
# === backend/apps/invoicing/urls.py ===
# =============================================================================
from django.urls import path

from .views import (InvoiceCreateView, InvoiceDetailView, InvoiceListView,
                    InvoicePdfView, InvoiceStatusUpdateView,
                    InvoiceSuggestedLaborLinesView)

urlpatterns = [
    path("service-records/<uuid:service_record_id>/invoice/",
         InvoiceCreateView.as_view(), name="invoice-create"),
    # 19 Oct 2026 (Phase 21, Task 21.2) -- read-only jasa suggestions.
    path("service-records/<uuid:service_record_id>/invoice/suggested-lines/",
         InvoiceSuggestedLaborLinesView.as_view(), name="invoice-suggested-lines"),

    path("invoices/",                    InvoiceListView.as_view(),         name="invoice-list"),
    path("invoices/<uuid:pk>/",          InvoiceDetailView.as_view(),       name="invoice-detail"),
    path("invoices/<uuid:pk>/status/",   InvoiceStatusUpdateView.as_view(), name="invoice-status-update"),
    path("invoices/<uuid:pk>/receipt.pdf", InvoicePdfView.as_view(),        name="invoice-pdf"),
]
