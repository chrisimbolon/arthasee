# =============================================================================
# === backend/apps/payments/events.py ===
# =============================================================================
"""
Arthasee — Payments Domain Events
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from apps.core.events.interfaces import DomainEvent


@dataclass(frozen=True)
class PaymentReceived(DomainEvent):
    """
    Fired every time Payment.record() successfully records a real
    payment — partial or full, doesn't matter (Chris's own explicit
    call): a partial payment is just as real a cash movement as one
    that happens to zero out balance_due, and the posting rule below
    doesn't distinguish between them.

    Posting rule (Roadmap v2.2): Dr Cash/Bank (1001/1101) / Cr
    Accounts Receivable (1201), both for `amount`. `method` is
    included specifically so the future accounting handler can choose
    between 1001 (Cash) and 1101 (Bank) — Payment.METHOD_CHOICES
    ("cash" vs bank_transfer/qris/card/other) is the only signal that
    exists for that choice; deciding it is the posting engine's job
    (posting_engine.cash_or_bank_account_code()), not this event's.

    Note on `amount`'s shape: unlike PartConsumed/WorkOrderCompleted/
    InvoiceIssued (all multiplication results, serialized with 4
    decimal places), Payment.amount is a raw stored DecimalField
    (decimal_places=2) — this event's amount will serialize as e.g.
    "250000.00", not "250000.0000".

    customer_name, added 2 Sep 2026 — real UX gap found on the Kas
    Harian dashboard: every memo across this whole posting matrix was
    built from a raw ID (event.payment_id), which reads fine in the
    audit-grade Jurnal page but meaninglessly in a friendly, owner-
    facing view. Frozen here from invoice.customer_name_snapshot —
    ALREADY a real, frozen field on Invoice (same identity-snapshot
    discipline this event's own amount/method fields already follow
    for money) — this is threading an existing snapshot one hop
    further, not inventing a new source of truth.
    """
    invoice_id: uuid.UUID
    payment_id: uuid.UUID
    amount: Decimal
    method: str
    customer_name: str
    event_type: str = field(init=False, default="PaymentReceived", kw_only=True)


@dataclass(frozen=True)
class SupplierPaymentMade(DomainEvent):
    """
    Fired when a supplier is actually paid — see
    apps.payments.models.SupplierPayment.record() (Sprint 3, Task
    3.3). Mirrors PaymentReceived's own shape, inverted: money
    leaving the business instead of arriving.

    Posting rule: Dr Accounts Payable (2001) / Cr Cash/Bank
    (1001/1101 depending on method), both for `amount` — reuses
    posting_engine.cash_or_bank_account_code() directly, the same
    shared mapping PaymentReceived and the InvoiceRefunded reversal
    already use. One real definition of "which account does this
    method map to," not a third copy.

    supplier_name, added 2 Sep 2026 — same real UX gap and same
    discipline as PaymentReceived.customer_name above. Frozen from
    supplier_invoice.supplier.name at record() time — no existing
    snapshot field for this one (unlike Invoice's own
    customer_name_snapshot), so this is a live read at the moment of
    payment, captured once into the event payload, never re-derived
    later from a Supplier row that could itself be renamed after
    the fact.
    """
    supplier_invoice_id: uuid.UUID
    supplier_payment_id: uuid.UUID
    amount: Decimal
    method: str
    supplier_name: str
    event_type: str = field(init=False, default="SupplierPaymentMade", kw_only=True)


@dataclass(frozen=True)
class OperatingExpenseRecorded(DomainEvent):
    """
    Fired when OperatingExpense.record() successfully records a real
    operating cost payment (27 Aug 2026 — Made's own confirmed real
    request: a guided "Catat Beban Operasional" form, an alternative
    to the generic Manual Adjusting Journal for exactly this
    recurring, routine kind of entry).

    Unlike every other event in this file, the DEBIT account is
    dynamic, not fixed — Made picks the real Expense account (Gaji,
    Sewa, Utilitas, etc.) per entry, excluding 6004 (reserved for the
    real, separate depreciation engine — see
    apps.payments.models.OperatingExpense's own docstring).
    account_code is frozen into this event's own payload at creation
    time, inside OperatingExpense.record()'s own transaction — same
    "capture once, don't recompute from a shifting database"
    discipline PurchaseReturned's own debit_account_code and
    QuickPurchaseRecorded's own payment_method already established.

    transaction_date, added 28 Aug 2026 — real bug found live:
    without this, journal_generator.post_for_event() fell back to
    occurred_at (when the event was PUBLISHED, i.e. "now"), silently
    ignoring the real, user-chosen paid_at date whenever it genuinely
    differed from today — a real expense entered for a real past or
    future date would post into the WRONG accounting period, exactly
    as if the real date had never been entered. Frozen here, same
    discipline as account_code above — the real business date, not
    re-derived from anything that could shift.

    account_name, added 2 Sep 2026 — same real UX gap and discipline
    as PaymentReceived.customer_name above. account_code alone is
    correct for posting but meaningless for a friendly memo; frozen
    from account.name (already resolved in record() to validate
    account_type/6004-exclusion) at the same moment account_code
    itself is frozen — no extra query, just threading a value that
    was already in hand.

    Posting rule: Dr {account_code} / Cr Cash (1001) or Bank (1101)
    depending on `method` — reuses the same shared
    cash_or_bank_account_code() mapping PaymentReceived/
    SupplierPaymentMade/QuickPurchaseRecorded already use.
    """
    operating_expense_id: uuid.UUID
    account_code: str
    account_name: str
    method: str
    amount: Decimal
    transaction_date: date
    event_type: str = field(init=False, default="OperatingExpenseRecorded", kw_only=True)


@dataclass(frozen=True)
class InternalCashMutationRecorded(DomainEvent):
    """
    Fired when InternalCashMutation.record() successfully records a
    real internal cash movement — the till being dropped to the bank,
    or (less commonly) a bank withdrawal made to top up the till. 1
    Sep 2026 — Made's own confirmed real request, arrived at while
    designing the Kas Harian dashboard: real workshops move physical
    cash to the bank regularly to manage theft risk, and that
    movement is a real fact this system had no way to record.

    Deliberately NOT a revenue or expense event — no P&L account is
    ever touched. `from_account_code`/`to_account_code` are always
    one of {"1001", "1101"} (Cash / Bank), enforced in
    InternalCashMutation.record() before this event is ever
    published — never re-validated here, same "frozen event payload"
    discipline OperatingExpenseRecorded's own account_code already
    established.

    transaction_date is frozen at creation for the same reason
    OperatingExpenseRecorded's own field is (Principle #12,
    Roadmap v2.7) — the real business date the mutation happened on,
    never re-derived from occurred_at.

    No display-name field needed here, unlike every other event in
    this file (2 Sep 2026 memo fix) — reports.daily_cash_activity()
    already builds this event's own friendly title independently,
    directly from from_account_code/to_account_code's real Account
    names, since both sides of a mutation are always real, known
    Chart-of-Accounts entries, never an external party's name.

    Posting rule: Dr {to_account_code} / Cr {from_account_code}, both
    for `amount` — a pure asset swap between two Cash/Bank accounts,
    zero income-statement impact.
    """
    internal_cash_mutation_id: uuid.UUID
    from_account_code: str
    to_account_code: str
    amount: Decimal
    transaction_date: date
    event_type: str = field(init=False, default="InternalCashMutationRecorded", kw_only=True)
