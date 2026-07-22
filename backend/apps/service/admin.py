from django.contrib import admin

from .models import (Customer, Part, PartUsage, ServiceRecord, StockAdjustment,
                     Vehicle)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display  = ("name", "phone", "stnk_name", "organization")
    search_fields = ("name", "phone", "stnk_name")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display  = (
        "plate_number", "model", "customer", "current_odometer_km",
        "last_service_date", "registration_expiry",
    )
    search_fields = ("plate_number", "model", "chassis_number", "engine_number")
    list_filter   = ("vehicle_type", "body_style")


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display  = ("vehicle", "service_date", "odometer_km")
    list_filter   = ("service_date",)


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
    # of sync with a "corrected" quantity. Delete/adjust via a fresh
    # StockAdjustment instead, same audit-trail discipline as the
    # rest of the codebase.
    readonly_fields = ("id", "part", "service_record", "quantity", "unit_price_at_time", "created_at")


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display  = ("part", "quantity_change", "reason", "created_by", "created_at")
    list_filter   = ("reason", "created_at")
