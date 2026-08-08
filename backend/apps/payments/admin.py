# =============================================================================
# === backend/apps/payments/admin.py ===
# =============================================================================
from django.contrib import admin

from .models import Payment, Refund, SupplierPayment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ("invoice", "amount", "method", "received_at", "received_by", "organization")
    list_filter   = ("method", "organization")
    search_fields = ("invoice__number", "reference")
    ordering      = ("-received_at",)
    readonly_fields = (
        "invoice", "amount", "method", "received_at",
        "reference", "notes", "received_by", "organization",
    )


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display  = ("invoice", "amount", "method", "refunded_at", "refunded_by", "organization")
    list_filter   = ("method", "organization")
    search_fields = ("invoice__number", "reference")
    ordering      = ("-refunded_at",)
    readonly_fields = (
        "invoice", "amount", "method", "refunded_at",
        "reference", "notes", "refunded_by", "organization",
    )


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display  = ("supplier_invoice", "amount", "method", "paid_at", "paid_by", "organization")
    list_filter   = ("method", "organization")
    search_fields = ("supplier_invoice__number", "reference")
    ordering      = ("-paid_at",)
    readonly_fields = (
        "supplier_invoice", "amount", "method", "paid_at",
        "reference", "notes", "paid_by", "organization",
    )
