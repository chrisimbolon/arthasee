# =============================================================================
# === backend/apps/purchasing/urls.py ===
# =============================================================================
from django.urls import path

from .views import (GoodsReceivedNoteDetailView,
                    GoodsReceivedNoteListCreateView, PurchaseOrderCancelView,
                    PurchaseOrderDetailView, PurchaseOrderLineItemAmendView,
                    PurchaseOrderListCreateView, PurchaseReturnDetailView,
                    PurchaseReturnListCreateView, QuickPurchaseDetailView,
                    QuickPurchaseListCreateView, SupplierDetailView,
                    SupplierInvoiceDetailView, SupplierInvoiceListCreateView,
                    SupplierInvoiceUploadAttachmentView,
                    SupplierListCreateView, SupplierReliabilityView)

urlpatterns = [
    path("suppliers/",                       SupplierListCreateView.as_view(),        name="supplier-list-create"),
    path("suppliers/<uuid:pk>/",              SupplierDetailView.as_view(),            name="supplier-detail"),
    path("purchase-orders/",                  PurchaseOrderListCreateView.as_view(),   name="purchase-order-list-create"),
    path("purchase-orders/<uuid:pk>/",        PurchaseOrderDetailView.as_view(),       name="purchase-order-detail"),
    path("purchase-orders/<uuid:pk>/cancel/", PurchaseOrderCancelView.as_view(),       name="purchase-order-cancel"),
    path("purchase-order-line-items/<uuid:pk>/amend/",
         PurchaseOrderLineItemAmendView.as_view(), name="purchase-order-line-item-amend"),
    path("goods-received-notes/",             GoodsReceivedNoteListCreateView.as_view(), name="grn-list-create"),
    path("goods-received-notes/<uuid:pk>/",   GoodsReceivedNoteDetailView.as_view(),    name="grn-detail"),
    path("supplier-invoices/",                SupplierInvoiceListCreateView.as_view(), name="supplier-invoice-list-create"),
    path("supplier-invoices/<uuid:pk>/",      SupplierInvoiceDetailView.as_view(),     name="supplier-invoice-detail"),
    path("supplier-invoices/<uuid:pk>/attachment/",
         SupplierInvoiceUploadAttachmentView.as_view(), name="supplier-invoice-upload-attachment"),
    path("purchase-returns/",                 PurchaseReturnListCreateView.as_view(),  name="purchase-return-list-create"),
    path("purchase-returns/<uuid:pk>/",       PurchaseReturnDetailView.as_view(),      name="purchase-return-detail"),
    path("supplier-reliability/",             SupplierReliabilityView.as_view(), name="supplier-reliability"),
    # Made's own confirmed exception, 25 Aug meeting — HARIAN/MINGGUAN
    # parts skip PurchaseOrder -> GoodsReceivedNote entirely.
    path("quick-purchases/",                  QuickPurchaseListCreateView.as_view(),   name="quick-purchase-list-create"),
    path("quick-purchases/<uuid:pk>/",        QuickPurchaseDetailView.as_view(),       name="quick-purchase-detail"),
]
