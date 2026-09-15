# =============================================================================
# === backend/apps/invoicing/urls.py ===
# =============================================================================
from django.urls import path

from .views import (InvoiceCreateView, InvoiceDetailView, InvoiceListView,
                    InvoicePdfView, InvoiceStatusUpdateView)

urlpatterns = [
    path("service-records/<uuid:service_record_id>/invoice/",
         InvoiceCreateView.as_view(), name="invoice-create"),

    path("invoices/",                    InvoiceListView.as_view(),         name="invoice-list"),
    path("invoices/<uuid:pk>/",          InvoiceDetailView.as_view(),       name="invoice-detail"),
    path("invoices/<uuid:pk>/status/",   InvoiceStatusUpdateView.as_view(), name="invoice-status-update"),
    path("invoices/<uuid:pk>/receipt.pdf", InvoicePdfView.as_view(),        name="invoice-pdf"),
]
