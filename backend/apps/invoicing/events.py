# =============================================================================
# === backend/apps/invoicing/events.py ===
# =============================================================================
"""
Arthasee — Invoicing Domain Events
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.core.events.interfaces import DomainEvent


@dataclass(frozen=True)
class InvoiceIssued(DomainEvent):
    """
    Fired exactly once, at the real DRAFT -> ISSUED transition — see
    apps.invoicing.views.InvoiceStatusUpdateView.patch() for exactly
    where. DRAFT is a one-way exit as of this same change (see that
    view's own docstring) — once an invoice leaves DRAFT, it can
    never return to it, which is what makes "exactly once" an actual
    guarantee here rather than just an intention.

    Posting rule (Roadmap v2.2): Dr Accounts Receivable (1201) / Cr
    Service Revenue (4001) for service_amount, Cr Parts Revenue
    (4002) for parts_amount. total must equal service_amount +
    parts_amount — that sum is the AR debit.

    ⚠️ Real, current limitation, not invented forward-compatibility:
    InvoiceLineItem.kind only has two real values today ("part",
    "labor") — there is no "sublet" line kind anywhere in this
    codebase, even though the Roadmap's own COA defines a Sublet
    Revenue account (4003) for exactly that case. This event can
    therefore only ever populate service_amount/parts_amount, never a
    sublet component. If/when a sublet line kind is ever added to
    InvoiceLineItem, this event AND its future accounting handler
    both need updating together — this event doesn't pretend to
    already support a case the schema doesn't have yet.
    """
    invoice_id: uuid.UUID
    service_amount: Decimal
    parts_amount: Decimal
    total: Decimal
    line_item_count: int
    event_type: str = field(init=False, default="InvoiceIssued", kw_only=True)


@dataclass(frozen=True)
class InvoiceCancelled(DomainEvent):
    """
    Fired when an ISSUED invoice with NO recorded payments is
    cancelled — the unpaid case (Task 2.3, Half A). Deliberately does
    NOT fire for DRAFT -> CANCELLED (nothing was ever posted for an
    invoice that never left DRAFT), and does NOT fire for a paid
    invoice being refunded (InvoiceRefunded, below — a structurally
    different reversal that credits Cash/Bank instead of AR).

    issued_event_id is Invoice.issued_event_id at the moment of
    cancellation — the exact InvoiceIssued.event_id whose
    JournalEntry needs reversing, carried explicitly rather than
    re-derived, so apps.accounting.cancellations never has to guess
    which posting this cancellation corresponds to. Nullable: a
    legacy invoice issued before this field existed genuinely has
    nothing on record to reverse.

    cancelled_by, added 6 Sep 2026 — real audit-trail gap found via a
    design-review trace (Sansan's own "who performed this reversal"
    question, Q57), not a live incident: apps.accounting.
    cancellations.reverse_for_event() never had a real actor to pass
    into JournalEntry.post()'s own created_by, since nothing upstream
    ever carried one. Nullable — this event is published from
    InvoiceStatusUpdateView.patch(), a real DRF view where
    request.user is always available in practice, but kept optional
    here rather than assumed required, matching this whole event
    system's own general discipline of not over-constraining a field
    a future caller might genuinely lack (a system-triggered
    cancellation with no human actor, say).
    """
    invoice_id: uuid.UUID
    issued_event_id: uuid.UUID | None
    cancelled_by: uuid.UUID | None = None
    event_type: str = field(init=False, default="InvoiceCancelled", kw_only=True)


@dataclass(frozen=True)
class InvoiceRefunded(DomainEvent):
    """
    Fired when a fully-PAID invoice is refunded — Task 2.3, Half B.
    Published from apps.payments.models.Refund.record(), not from
    anywhere in this app — same cross-app pattern as
    apps.inventory.events.PartConsumed (defined where it conceptually
    belongs — an Invoice lifecycle event lives with the others here —
    published wherever the real trigger actually is).

    Posting rule: reverses ONLY the revenue lines of the original
    InvoiceIssued posting — Dr Service/Parts Revenue (matching
    whatever was actually credited) / Cr Cash(1001) or Bank(1101)
    depending on method. Deliberately does NOT touch Accounts
    Receivable (1201) — unlike InvoiceCancelled's generic line-flip,
    AR is already correctly at zero by the time an invoice reaches
    PAID (cleared by the PaymentReceived postings that got it there);
    re-crediting it here would push it negative. See
    apps.accounting.cancellations.reverse_for_refund_event() for the
    actual bespoke reversal — NOT the same generic flip
    InvoiceCancelled uses.

    issued_event_id mirrors InvoiceCancelled's own field exactly.
    amount/method describe the refund itself for audit-trail
    readability; the reversal's own dollar figures are still read
    from the original JournalEntry's real lines, not recomputed from
    these — same "trust the real ledger, not the publisher"
    discipline as Half A.

    refunded_by, added 6 Sep 2026 — same real audit-trail gap and
    same discipline as InvoiceCancelled.cancelled_by above.
    Refund.record() already has a real refunded_by parameter (the
    acting CustomUser, stored on the Refund row itself) — this simply
    threads that same value one hop further into the event payload,
    no new query, no new source of truth, matching this whole
    matrix's own established "thread what's already in hand" pattern
    (customer_name/supplier_name/account_name all followed the exact
    same approach).
    """
    invoice_id: uuid.UUID
    refund_id: uuid.UUID
    issued_event_id: uuid.UUID | None
    amount: Decimal
    method: str
    refunded_by: uuid.UUID | None = None
    event_type: str = field(init=False, default="InvoiceRefunded", kw_only=True)


@dataclass(frozen=True)
class InvoicePartAdjusted(DomainEvent):
    """
    22 Oct 2026 (Phase 21, Task C2) — a part added to, or returned to stock
    from, a DRAFT invoice. Made's note, 12 Sep 2026: "Waktu invoice di posisi
    draft, masih bisa tambah & kurang barang / jasa."

    By the time an invoice exists its WorkOrder is closed and its parts'
    cost has already moved WIP -> COGS (WorkOrderCompleted). So a part
    changed on the draft goes straight between Inventory and COGS:

      direction "added"    -> Dr COGS Sparepart (5001) / Cr Inventory (1301)
      direction "returned" -> Dr Inventory (1301) / Cr COGS Sparepart (5001)

    both for `amount` = quantity x unit_cost (the part's COST, never its
    selling price). A "returned" line uses the cost frozen on that invoice
    line when it was created (InvoiceLineItem.unit_cost), so it undoes
    exactly what was booked. "Tidak ditagih" (given free) publishes nothing:
    the part really was used, so its cost correctly stays in COGS.

    Published by Invoice.add_part_line() / Invoice.return_part_line().
    transaction_date frozen at creation (Cheat Sheet section 4).
    """
    invoice_id: uuid.UUID
    part_id: uuid.UUID
    direction: str
    quantity: Decimal
    unit_cost: Decimal
    amount: Decimal
    transaction_date: date
    event_type: str = field(init=False, default="InvoicePartAdjusted", kw_only=True)
