# =============================================================================
# === backend/apps/accounting/cancellations.py ===
# =============================================================================
"""
Arthasee — Reversal & Cancellation Posting (Task 2.3, Half A)

Genuinely different concern from posting_engine.py / journal_generator.py
— those post NEW economic facts from domain events, using zero ORM
queries by design (see posting_engine.py's own module docstring).
This file reverses a PREVIOUSLY posted fact when a billing document
gets cancelled, which fundamentally REQUIRES a database lookup — the
original JournalEntry has to actually be found before anything can
be reversed. Deliberately not forced into posting_engine.py's
query-free shape; this gets its own file, exactly as Sprint Plan
v1.1's own Task 2.3 already specified.

Handles InvoiceCancelled only, for now (Half A — unpaid invoices).
InvoiceRefunded (Half B, paid invoices) is a deliberately separate,
not-yet-built event with its own bespoke reversal shape — it credits
Cash/Bank, not AR, so it can't reuse the generic line-flip below.
"""
from apps.accounting.models import JournalEntry
from apps.organizations.models import Organization


def reverse_for_event(event) -> JournalEntry | None:
    """
    Returns the reversing JournalEntry, or None if there was nothing
    to reverse:
      - event.issued_event_id is None — a legacy invoice issued
        before that field existed, or one whose original
        InvoiceIssued never actually posted (e.g. the Chart of
        Accounts wasn't seeded yet when it tried).
      - No JournalEntry exists with that reference_event_id — same
        "original posting never really happened" case, found instead
        of assumed.
      - This cancellation was already reversed before (idempotency
        guard, same discipline as journal_generator.post_for_event —
        checked first, before any lookup work happens).
    """
    if JournalEntry.objects.filter(reference_event_id=event.event_id).exists():
        return None

    if event.issued_event_id is None:
        return None

    original = JournalEntry.objects.filter(reference_event_id=event.issued_event_id).first()
    if original is None:
        return None

    organization = Organization.objects.get(id=event.organization_id)

    # Flip every line of the original entry — same account, same
    # amount, opposite side. Correct by construction: whatever was
    # ACTUALLY posted is exactly what gets undone, for any number of
    # lines or accounts — no need to hardcode 4001/4002 here and risk
    # drifting from what InvoiceIssued really posted for this
    # specific invoice (a labor-only or parts-only invoice only ever
    # had one revenue line to begin with — this handles that
    # correctly without any special-casing).
    lines = [
        {
            "account": line.account,
            "debit":  line.credit_amount if line.credit_amount > 0 else None,
            "credit": line.debit_amount if line.debit_amount > 0 else None,
        }
        for line in original.lines.all()
    ]

    return JournalEntry.post(
        organization=organization,
        posting_date=event.occurred_at.date(),
        source=JournalEntry.Source.DOMAIN_EVENT,
        event_type=event.event_type,
        reference_event_id=event.event_id,
        memo=f"Reversal of {original.entry_number} — invoice cancelled",
        lines=lines,
    )
