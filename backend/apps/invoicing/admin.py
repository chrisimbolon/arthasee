from django.contrib import admin

from .models import Invoice, InvoiceLineItem, InvoiceSequence


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 0
    readonly_fields = ("kind", "description", "quantity", "unit_price", "part")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display  = ("number", "customer_name_snapshot", "license_plate_snapshot", "status", "total", "created_at")
    list_filter   = ("status", "year")
    search_fields = ("number", "customer_name_snapshot", "license_plate_snapshot")
    inlines       = [InvoiceLineItemInline]
    readonly_fields = (
        "number", "sequence_number", "year",
        "customer_name_snapshot", "license_plate_snapshot", "created_at",
    )


@admin.register(InvoiceSequence)
class InvoiceSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "year", "last_sequence")
