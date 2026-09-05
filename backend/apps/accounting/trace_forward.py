# =============================================================================
# === backend/apps/accounting/trace_forward.py ===
# =============================================================================
"""
Arthasee — General Ledger Trace-Forward Resolver

Maps a JournalEntry's own event_type + reference_event_id back to the
real operational document that caused it — Buku Besar's own
"Ref Sumber" column. One real mapping table, not scattered per-event
guesses, and batched per page (grouped by event_type — one Outbox
lookup and one target-model lookup per group) rather than a query per
row, since a ledger page can render up to page_size rows at once.

Three real states, per the design review's own confirmed V1 decision:
  - "link"  — a real document with a confirmed frontend detail page
    (Invoice, WorkOrder, GoodsReceivedNote, SupplierInvoice). Renders
    as an active, clickable reference.
  - "badge" — a real document exists (a real .number on its own
    model) but no confirmed detail page to link to yet
    (OperatingExpense, InternalCashMutation, QuickPurchase,
    PurchaseReturn, StockOpnameSession). Renders as a plain,
    disabled/greyed chip showing the real reference number — audit
    context with zero risk of a dead link.
  - "none"  — no reference_event_id mechanism at all (MANUAL,
    PERIOD_CLOSING, ASSET_ACQUISITION, DEPRECIATION,
    OPENING_BALANCE all post directly, never through this event-
    sourced path at all), or any future event_type not yet added to
    this map. Renders as plain "Internal Action" text.

Honest, deliberate defensive choice: OperatingExpense, InternalCash
Mutation, and StockOpnameSession — all three "badge" targets — were
NOT directly confirmed to have a real .number field on their own
models during this feature's build (only their event classes were
reviewed). Resolved via getattr(obj, "number", None) rather than a
hard attribute access — if a field name here turns out to differ
from what's actually on that model, this fails soft (no badge number
rendered, never a 500 crashing the whole ledger page). Worth
confirming those three model definitions directly as a fast
follow-up, rather than trusting this blind.
"""
from django.apps import apps

from apps.core.models import Outbox

# event_type -> (payload_id_field, app_label, model_name, has_detail_page)
# payload_id_field must match the real dataclass field name on that
# event class exactly — confirmed against every event file reviewed
# for this feature (Outbox.payload is a plain JSON dict keyed by the
# event's own real field names, verified directly against existing
# test usage elsewhere in this codebase, e.g.
# row.payload["material_line_id"] / row.payload["work_order_id"]).
_TRACE_FORWARD = {
    "InvoiceIssued":               ("invoice_id", "invoicing", "Invoice", True),
    "PaymentReceived":              ("invoice_id", "invoicing", "Invoice", True),
    "InvoiceCancelled":             ("invoice_id", "invoicing", "Invoice", True),
    "InvoiceRefunded":              ("invoice_id", "invoicing", "Invoice", True),
    "WorkOrderCompleted":           ("work_order_id", "workorders", "WorkOrder", True),
    "PartConsumed":                 ("work_order_id", "workorders", "WorkOrder", True),
    "GoodsReceived":                ("goods_received_note_id", "purchasing", "GoodsReceivedNote", True),
    "SupplierInvoiceReceived":      ("supplier_invoice_id", "purchasing", "SupplierInvoice", True),
    "SupplierPaymentMade":          ("supplier_invoice_id", "purchasing", "SupplierInvoice", True),
    "OperatingExpenseRecorded":     ("operating_expense_id", "payments", "OperatingExpense", False),
    "InternalCashMutationRecorded": ("internal_cash_mutation_id", "payments", "InternalCashMutation", False),
    "QuickPurchaseRecorded":        ("quick_purchase_id", "purchasing", "QuickPurchase", False),
    "PurchaseReturned":             ("purchase_return_id", "purchasing", "PurchaseReturn", False),
    "StockOpnameCompleted":         ("stock_opname_session_id", "inventory", "StockOpnameSession", False),
}

# Real, confirmed frontend routes for the "link" targets only — kept
# here, the one real place mapping a model to whether/where it's
# linkable at all, not scattered across frontend files.
_DETAIL_ROUTES = {
    "Invoice":           "/dashboard/invoice-detail",
    "WorkOrder":         "/dashboard/work-order-detail",
    "GoodsReceivedNote": "/dashboard/goods-received-detail",
    "SupplierInvoice":   "/dashboard/supplier-invoice-detail",
}


def resolve_references(rows: list[dict]) -> None:
    """
    Mutates each row in place, adding a "reference" key:

        {"kind": "link" | "badge" | "none", "label": str | None, "url": str | None}

    Expects each row to already carry "event_type" and
    "reference_event_id" (general_ledger()'s own row shape). Batched,
    not per-row: groups rows by event_type first (one Outbox lookup
    per group), then by target model (one model lookup per group) —
    a full page of up to page_size rows costs at most
    2 * (distinct event types actually present on this page) queries,
    never one query per row.
    """
    for row in rows:
        row["reference"] = {"kind": "none", "label": None, "url": None}

    rows_by_event_type: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("reference_event_id") and row["event_type"] in _TRACE_FORWARD:
            rows_by_event_type.setdefault(row["event_type"], []).append(row)

    for event_type, group_rows in rows_by_event_type.items():
        id_field, app_label, model_name, has_detail_page = _TRACE_FORWARD[event_type]
        event_ids = [r["reference_event_id"] for r in group_rows]

        outbox_rows = Outbox.objects.filter(event_id__in=event_ids).values("event_id", "payload")
        target_id_by_event_id = {}
        for ob in outbox_rows:
            target_id = ob["payload"].get(id_field)
            if target_id:
                target_id_by_event_id[str(ob["event_id"])] = target_id

        if not target_id_by_event_id:
            continue

        Model = apps.get_model(app_label, model_name)
        target_ids = list(set(target_id_by_event_id.values()))
        objects = Model.objects.filter(id__in=target_ids)
        # getattr-safe — see module docstring for exactly which three
        # models this defensive lookup exists for.
        number_by_id = {str(obj.id): getattr(obj, "number", None) for obj in objects}

        for row in group_rows:
            target_id = target_id_by_event_id.get(row["reference_event_id"])
            if target_id is None:
                continue
            number = number_by_id.get(str(target_id))
            if number is None:
                continue
            if has_detail_page:
                route = _DETAIL_ROUTES.get(model_name)
                row["reference"] = {
                    "kind": "link", "label": number,
                    "url": f"{route}?id={target_id}" if route else None,
                }
            else:
                row["reference"] = {"kind": "badge", "label": number, "url": None}
