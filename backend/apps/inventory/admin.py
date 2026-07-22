from django.contrib import admin

from .models import Part, PartUsage, StockAdjustment


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display  = ("name", "sku", "unit", "current_stock", "unit_price", "organization")
    search_fields = ("name", "sku")


@admin.register(PartUsage)
class PartUsageAdmin(admin.ModelAdmin):
    list_display  = ("part", "service_record", "quantity", "unit_price_at_time", "created_at")
    list_filter   = ("created_at",)
    # Append-only, same as ServiceRecord — editing a usage after the
    # fact would leave the stock deduction it already triggered out
    # of sync with a "corrected" quantity.
    readonly_fields = ("id", "part", "service_record", "quantity", "unit_price_at_time", "created_at")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display  = ("part", "quantity_change", "reason", "created_by", "created_at")
    list_filter   = ("reason", "created_at")
