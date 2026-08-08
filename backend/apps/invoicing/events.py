# =============================================================================
# === backend/apps/invoicing/events.py ===
# =============================================================================
"""
Arthasee — Invoicing Domain Events
"""
import uuid
from dataclasses import dataclass, field
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
    invoice that never left DRAFT — publishing an event with nothing
    to reverse would just be audit-trail noise), and does NOT fire
    for a paid invoice being refunded (InvoiceRefunded, Task 2.3 Half
    B — a structurally different reversal that credits Cash/Bank
    instead of AR, not yet built).

    issued_event_id is Invoice.issued_event_id at the moment of
    cancellation — the exact InvoiceIssued.event_id whose
    JournalEntry needs reversing, carried explicitly rather than
    re-derived, so apps.accounting.cancellations never has to guess
    which posting this cancellation corresponds to. Nullable: a
    legacy invoice issued before this field existed (or one whose
    original InvoiceIssued never actually posted — e.g. unseeded COA
    at the time) genuinely has nothing on record to reverse.
    cancellations.reverse_for_event() treats None as "nothing to
    reverse," not an error.

    No amount fields here on purpose — unlike InvoiceIssued, which
    computes its own amounts, this event doesn't carry a dollar
    figure at all. The reversal reads its numbers directly from the
    ORIGINAL JournalEntry's own posted lines (see
    apps.accounting.cancellations), guaranteeing the reversal matches
    what's REALLY in the ledger rather than what this event's
    publisher believes should be there.
    """
    invoice_id: uuid.UUID
    issued_event_id: uuid.UUID | None
    event_type: str = field(init=False, default="InvoiceCancelled", kw_only=True)
