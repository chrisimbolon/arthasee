# =============================================================================
# === backend/apps/payments/events.py ===
# =============================================================================
"""
Arthasee — Payments Domain Events
"""
import uuid
from dataclasses import dataclass, field
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
    """
    invoice_id: uuid.UUID
    payment_id: uuid.UUID
    amount: Decimal
    method: str
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
    """
    supplier_invoice_id: uuid.UUID
    supplier_payment_id: uuid.UUID
    amount: Decimal
    method: str
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

    Posting rule: Dr {account_code} / Cr Cash (1001) or Bank (1101)
    depending on `method` — reuses the same shared
    cash_or_bank_account_code() mapping PaymentReceived/
    SupplierPaymentMade/QuickPurchaseRecorded already use.
    """
    operating_expense_id: uuid.UUID
    account_code: str
    method: str
    amount: Decimal
    event_type: str = field(init=False, default="OperatingExpenseRecorded", kw_only=True)
