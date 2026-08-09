# =============================================================================
# === backend/apps/purchasing/urls.py ===
# =============================================================================
from django.urls import path

from .views import (GoodsReceivedNoteDetailView, GoodsReceivedNoteListCreateView,
                    SupplierDetailView, SupplierInvoiceDetailView,
                    SupplierInvoiceListCreateView, SupplierListCreateView)

urlpatterns = [
    path("suppliers/",                       SupplierListCreateView.as_view(),        name="supplier-list-create"),
    path("suppliers/<uuid:pk>/",              SupplierDetailView.as_view(),            name="supplier-detail"),
    path("goods-received-notes/",             GoodsReceivedNoteListCreateView.as_view(), name="grn-list-create"),
    path("goods-received-notes/<uuid:pk>/",   GoodsReceivedNoteDetailView.as_view(),    name="grn-detail"),
    path("supplier-invoices/",                SupplierInvoiceListCreateView.as_view(), name="supplier-invoice-list-create"),
    path("supplier-invoices/<uuid:pk>/",      SupplierInvoiceDetailView.as_view(),     name="supplier-invoice-detail"),
]
