# =============================================================================
# === backend/apps/accounting/admin.py ===
# =============================================================================
from django.contrib import admin

from apps.accounting.models import (
    Account,
    AccountingPeriod,
    JournalEntry,
    JournalEntrySequence,
    JournalLine,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display  = ("code", "name", "account_type", "normal_balance", "organization", "is_active")
    list_filter   = ("account_type", "normal_balance", "is_active", "organization")
    search_fields = ("code", "name")
    ordering      = ("organization", "code")


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("organization", "start_date", "end_date", "is_closed", "is_locked")
    list_filter  = ("is_closed", "is_locked", "organization")


class JournalLineInline(admin.TabularInline):
    model = JournalLine
    extra = 0
    readonly_fields = ("account", "debit_amount", "credit_amount", "description")
    can_delete = False


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display  = ("entry_number", "organization", "posting_date", "source", "event_type", "status")
    list_filter   = ("source", "status", "organization")
    search_fields = ("entry_number", "event_type", "reference_event_id", "memo")
    ordering      = ("-posting_date", "-sequence_number")
    inlines       = [JournalLineInline]
    # Journal entries are only ever created via JournalEntry.post() —
    # admin is for inspection/audit, not manual creation, until Phase
    # 4's dedicated manual-adjustment endpoint exists.
    readonly_fields = (
        "entry_number", "sequence_number", "source", "event_type",
        "reference_event_id", "status",
    )


@admin.register(JournalEntrySequence)
class JournalEntrySequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")
