# =============================================================================
# === backend/apps/purchasing/admin.py ===
# =============================================================================
from django.contrib import admin

from .models import (GoodsReceivedNote, GoodsReceivedNoteLineItem,
                     GoodsReceivedNoteSequence, Supplier, SupplierInvoice,
                     SupplierInvoiceSequence)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display  = ("name", "contact_person", "phone", "is_active", "organization")
    list_filter   = ("is_active", "organization")
    search_fields = ("name", "contact_person", "phone", "email")


class GoodsReceivedNoteLineItemInline(admin.TabularInline):
    model = GoodsReceivedNoteLineItem
    extra = 0
    readonly_fields = ("part", "quantity", "unit_cost")
    can_delete = False


@admin.register(GoodsReceivedNote)
class GoodsReceivedNoteAdmin(admin.ModelAdmin):
    list_display  = ("number", "supplier", "received_at", "supplier_invoice", "organization")
    list_filter   = ("organization",)
    search_fields = ("number", "reference", "supplier__name")
    ordering      = ("-received_at",)
    inlines       = [GoodsReceivedNoteLineItemInline]
    # Only ever created via GoodsReceivedNote.receive() — admin is
    # for inspection/audit, matching every other document-like model
    # in this codebase (Invoice, JournalEntry, ...).
    readonly_fields = ("number", "sequence_number", "supplier", "supplier_invoice")


@admin.register(SupplierInvoice)
class SupplierInvoiceAdmin(admin.ModelAdmin):
    list_display  = ("number", "supplier", "amount", "status", "invoice_date", "organization")
    list_filter   = ("status", "organization")
    search_fields = ("number", "supplier_invoice_number", "supplier__name")
    ordering      = ("-invoice_date",)
    readonly_fields = ("number", "sequence_number", "supplier", "status")


@admin.register(GoodsReceivedNoteSequence)
class GoodsReceivedNoteSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")


@admin.register(SupplierInvoiceSequence)
class SupplierInvoiceSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")
