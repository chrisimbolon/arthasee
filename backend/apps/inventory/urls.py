from django.urls import path

from .views import (PartDetailView, PartListView, PartMovementHistoryView,
                    PartStockSummaryView, PartUsageListView,
                    StockAdjustmentListView, StockOpnameSessionCompleteView,
                    StockOpnameSessionDetailView, StockOpnameSessionListView)

urlpatterns = [
    # Placed before parts/<uuid:pk>/ as a clean, predictable
    # convention — not strictly required for correctness here, since
    # Django's uuid converter matches against a strict regex and
    # "stock-summary" simply fails that pattern, falling through to
    # the next url() automatically either way. Worth being precise
    # about that rather than asserting a risk that isn't real.
    path("parts/stock-summary/", PartStockSummaryView.as_view(), name="part-stock-summary"),

    path("parts/",              PartListView.as_view(),   name="part-list"),
    path("parts/<uuid:pk>/",    PartDetailView.as_view(), name="part-detail"),

    path("parts/<uuid:part_id>/adjustments/",
         StockAdjustmentListView.as_view(), name="stock-adjustment-list"),
    path("parts/<uuid:part_id>/movements/",
         PartMovementHistoryView.as_view(), name="part-movement-history"),

    path("service-records/<uuid:service_record_id>/part-usages/",
         PartUsageListView.as_view(), name="part-usage-list"),

    # Sprint 7, Task 7.3 — Stock Opname. Deliberately flat, same
    # "stock-opname/", not "inventory/stock-opname/" — matching every
    # route above exactly. Same ordering discipline as parts/
    # above: the more specific "<pk>/complete/" path is placed after
    # the plain "<pk>/" path per Django convention (most specific
    # last isn't required here either, since "complete" can't match
    # the bare <uuid:pk> converter — same non-issue as stock-summary/
    # above — but grouped together for readability).
    path("stock-opname/",             StockOpnameSessionListView.as_view(),    name="stock-opname-list"),
    path("stock-opname/<uuid:pk>/",   StockOpnameSessionDetailView.as_view(),  name="stock-opname-detail"),
    path("stock-opname/<uuid:pk>/complete/",
         StockOpnameSessionCompleteView.as_view(), name="stock-opname-complete"),
]
