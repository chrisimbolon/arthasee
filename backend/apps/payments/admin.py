# =============================================================================
# === backend/apps/payments/admin.py ===
# =============================================================================
from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ("invoice", "amount", "method", "received_at", "received_by", "organization")
    list_filter   = ("method", "organization")
    search_fields = ("invoice__number", "reference")
    ordering      = ("-received_at",)
    # Payments are only ever created via Payment.record() — admin is
    # for inspection/audit, matching JournalEntryAdmin's own
    # read-only posture in apps.accounting.admin.
    readonly_fields = (
        "invoice", "amount", "method", "received_at",
        "reference", "notes", "received_by", "organization",
    )
