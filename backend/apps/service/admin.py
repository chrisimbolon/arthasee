from django.contrib import admin

from .models import (Customer, CustomerFieldChange, ServiceItem,
                     ServiceItemChange, ServiceItemPrice, ServiceRecord,
                     Vehicle, VehicleFieldChange)


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

@admin.register(CustomerFieldChange)
class CustomerFieldChangeAdmin(admin.ModelAdmin):
    """
    13 Sep 2026 — real lockdown, same discipline every other real
    audit-adjacent model in this codebase already gets (JournalEntry,
    AccountingPeriod, Account's own classification fields) — an
    EDITABLE audit trail is not a trustworthy audit trail. Every
    field readonly, add/delete both blocked outright — the only real
    way a row here is ever created is Customer.apply_edit() itself
    (models.py), never a direct Admin write.
    """
    list_display  = ("customer", "field_label", "old_value", "new_value", "changed_by", "changed_at")
    list_filter   = ("field_name", "organization")
    search_fields = ("customer__name", "field_label")
    ordering      = ("-changed_at",)
    readonly_fields = (
        "organization", "customer", "field_name", "field_label",
        "old_value", "new_value", "changed_by", "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(VehicleFieldChange)
class VehicleFieldChangeAdmin(admin.ModelAdmin):
    """
    14 Sep 2026 — same real lockdown discipline as
    CustomerFieldChangeAdmin — an editable audit trail is not a
    trustworthy audit trail. Every field readonly, add/delete both
    blocked — the only real way a row here is ever created is
    Vehicle.apply_edit() itself (models.py).
    """
    list_display  = ("vehicle", "field_label", "old_value", "new_value", "changed_by", "changed_at")
    list_filter   = ("field_name", "organization")
    search_fields = ("vehicle__plate_number", "field_label")
    ordering      = ("-changed_at",)
    readonly_fields = (
        "organization", "vehicle", "field_name", "field_label",
        "old_value", "new_value", "changed_by", "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False    


# 20 Oct 2026 (Phase 21, Task 21.3) — Daftar Jasa is read-only in Admin
# (Cheat Sheet section 11, both questions): every price change must go
# through ServiceItem.record()/apply_edit(), which write the change
# history — an Admin edit would silently skip it.
class ServiceItemPriceInline(admin.TabularInline):
    model = ServiceItemPrice
    extra = 0
    can_delete = False
    readonly_fields = ("body_style", "price")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ServiceItem)
class ServiceItemAdmin(admin.ModelAdmin):
    list_display  = ("name", "organization", "default_price", "is_active", "updated_at")
    list_filter   = ("is_active", "organization")
    search_fields = ("name",)
    inlines       = (ServiceItemPriceInline,)
    readonly_fields = (
        "organization", "name", "default_price", "is_active", "created_by", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ServiceItemChange)
class ServiceItemChangeAdmin(admin.ModelAdmin):
    list_display  = ("service_item", "field_label", "old_value", "new_value", "changed_by", "changed_at")
    list_filter   = ("organization",)
    search_fields = ("service_item__name", "field_label")
    ordering      = ("-changed_at",)
    readonly_fields = (
        "organization", "service_item", "field_label", "old_value", "new_value", "changed_by", "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
