# =============================================================================
# === backend/apps/invoicing/urls.py ===
# =============================================================================
from django.urls import path

from .views import (InvoiceCreateView, InvoiceDetailView,
                    InvoiceLaborLineDetailView, InvoiceLaborLineListView,
                    InvoiceListView, InvoicePartLineActionView,
                    InvoicePartLineListView, InvoicePdfView,
                    InvoiceStatusUpdateView, InvoiceSuggestedLaborLinesView)

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
    # 22 Oct 2026 (Phase 21, Task C1) -- jasa lines on a DRAFT invoice.
    path("invoices/<uuid:pk>/line-items/",  InvoiceLaborLineListView.as_view(),   name="invoice-labor-line-add"),
    path("invoices/line-items/<uuid:pk>/",  InvoiceLaborLineDetailView.as_view(), name="invoice-labor-line-detail"),
    # 22 Oct 2026 (Phase 21, Task C2) -- parts on a DRAFT invoice.
    path("invoices/<uuid:pk>/part-lines/",  InvoicePartLineListView.as_view(),   name="invoice-part-line-add"),
    path("invoices/part-lines/<uuid:pk>/<str:action>/", InvoicePartLineActionView.as_view(), name="invoice-part-line-action"),
]
