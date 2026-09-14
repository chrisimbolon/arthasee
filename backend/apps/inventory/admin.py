from django.contrib import admin

from .models import Part, PartFieldChange, PartUsage, StockAdjustment


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

@admin.register(PartFieldChange)
class PartFieldChangeAdmin(admin.ModelAdmin):
    """
    14 Sep 2026 — same real lockdown discipline as
    CustomerFieldChangeAdmin/VehicleFieldChangeAdmin (apps.service)
    — an editable audit trail is not a trustworthy audit trail.
    Every field readonly, add/delete both blocked — the only real
    way a row here is ever created is Part.apply_edit() itself
    (models.py).
    """
    list_display  = ("part", "field_label", "old_value", "new_value", "changed_by", "changed_at")
    list_filter   = ("field_name", "organization")
    search_fields = ("part__name", "part__sku", "field_label")
    ordering      = ("-changed_at",)
    readonly_fields = (
        "organization", "part", "field_name", "field_label",
        "old_value", "new_value", "changed_by", "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False