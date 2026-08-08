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
    """
    invoice_id: uuid.UUID
    issued_event_id: uuid.UUID | None
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
    """
    invoice_id: uuid.UUID
    refund_id: uuid.UUID
    issued_event_id: uuid.UUID | None
    amount: Decimal
    method: str
    event_type: str = field(init=False, default="InvoiceRefunded", kw_only=True)
