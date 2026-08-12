from django.urls import path

from .views import (PartDetailView, PartListView, PartMovementHistoryView,
                    PartStockSummaryView, PartUsageListView,
                    StockAdjustmentListView)

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
]