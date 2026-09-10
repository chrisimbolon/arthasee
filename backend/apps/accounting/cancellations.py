# =============================================================================
# === backend/apps/accounting/cancellations.py ===
# =============================================================================
"""
Arthasee — Reversal & Cancellation Posting (Task 2.3)

Genuinely different concern from posting_engine.py / journal_generator.py
— those post NEW economic facts from domain events, using zero ORM
queries by design (see posting_engine.py's own module docstring).
This file reverses a PREVIOUSLY posted fact when a billing document
gets cancelled or refunded, which fundamentally REQUIRES a database
lookup — the original JournalEntry has to actually be found before
anything can be reversed.

Two reversal shapes, not one — reverse_for_event() (Half A, unpaid
cancellation) and reverse_for_refund_event() (Half B, paid refund)
are deliberately separate functions, not a shared "reverse whatever
you find" helper. By the time an invoice reaches PAID, Accounts
Receivable is already correctly at zero (cleared by the
PaymentReceived postings that got it there) — Half A's generic
line-flip would re-credit AR and push it negative if applied to a
paid invoice's original entry. Half B touches only the revenue lines
and credits Cash/Bank instead. Same underlying JournalEntry.post()
write path, genuinely different accounting logic above it.

6 Sep 2026 — both functions now thread a real actor into their own
reversing JournalEntry's created_by, closing a real audit-trail gap
found via a design-review trace (Sansan's own "who performed this
reversal" question, Q57), not a live incident: neither reversal ever
had a real user attached before, since neither event carried one.
InvoiceCancelled.cancelled_by/InvoiceRefunded.refunded_by are both
nullable UUIDs, not real model instances — resolved here via a soft
.filter().first() lookup, same "a since-deleted user must never
crash this" discipline every other created_by/received_by field in
this codebase already follows (all SET_NULL, all optional).
"""
from decimal import Decimal

from apps.accounting.models import Account, JournalEntry
from apps.accounting.posting_engine import cash_or_bank_account_code
from apps.organizations.models import Organization
from django.utils import timezone


def _resolve_actor(user_id):
    """
    Shared helper for both reversal functions below — a real user
    instance if user_id is set and still exists, None otherwise.
    Never raises: a since-deleted user is a real, anticipated state
    (every actor FK in this codebase is SET_NULL), not an error
    condition worth crashing a reversal over.
    """
    if user_id is None:
        return None
    from apps.authentication.models import CustomUser
    return CustomUser.objects.filter(pk=user_id).first()

def _safe_posting_date(event):
    """
    9 Sep 2026 — real fix, backporting journal_generator.
    post_for_event()'s own 5 Sep 2026 timezone fix, missed here at
    the time: occurred_at is a UTC-aware datetime under this
    project's real USE_TZ=True / TIME_ZONE="Asia/Jakarta" (UTC+7)
    settings — calling .date() directly on it extracts the UTC
    calendar day, not the shop's real local one, silently misdating
    any reversal posted between local midnight and 7am local time.
    timezone.localtime() converts back to the project's configured
    local zone first. Shared here, not duplicated across both
    reversal functions below — same "one real definition" discipline
    cash_or_bank_account_code() already established in
    posting_engine.py. Defensive is_aware() guard mirrors journal_
    generator.py's own — occurred_at is expected to always be aware,
    but this falls back to the raw date rather than crash if that
    assumption is ever wrong for some caller this fix didn't see.
    """
    if timezone.is_aware(event.occurred_at):
        return timezone.localtime(event.occurred_at).date()
    return event.occurred_at.date()

def reverse_for_event(event) -> JournalEntry | None:
    """
    Task 2.3, Half A — unpaid invoice cancellation. Returns the
    reversing JournalEntry, or None if there was nothing to reverse:
      - event.issued_event_id is None — a legacy invoice issued
        before that field existed, or one whose original
        InvoiceIssued never actually posted (e.g. the Chart of
        Accounts wasn't seeded yet when it tried).
      - No JournalEntry exists with that reference_event_id — same
        "original posting never really happened" case, found instead
        of assumed.
      - This cancellation was already reversed before (idempotency
        guard, checked first, before any lookup work happens).
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
    # specific invoice.
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
        posting_date=_safe_posting_date(event),
        source=JournalEntry.Source.DOMAIN_EVENT,
        event_type=event.event_type,
        reference_event_id=event.event_id,
        memo=f"Reversal of {original.entry_number} — invoice cancelled",
        # 6 Sep 2026 — real audit-trail fix. See module docstring —
        # event.cancelled_by is None until invoicing/views.py's own
        # InvoiceStatusUpdateView.patch() is updated to actually
        # thread the acting user through when publishing
        # InvoiceCancelled; this resolution is already correct and
        # ready for that moment, not a no-op waiting on it.
        created_by=_resolve_actor(getattr(event, "cancelled_by", None)),
        lines=lines,
    )


def reverse_for_refund_event(event) -> JournalEntry | None:
    """
    Task 2.3, Half B — paid invoice refund. Bespoke, NOT a reuse of
    reverse_for_event()'s generic flip — see this module's own
    docstring for exactly why. Touches only the revenue lines of the
    original InvoiceIssued posting, crediting Cash(1001) or
    Bank(1101) based on the refund's own method (independent of
    whatever method the original payment used).

    Same three no-op cases as reverse_for_event(): already reversed,
    issued_event_id is None, or no original entry found.
    """
    if JournalEntry.objects.filter(reference_event_id=event.event_id).exists():
        return None

    if event.issued_event_id is None:
        return None

    original = JournalEntry.objects.filter(reference_event_id=event.issued_event_id).first()
    if original is None:
        return None

    organization = Organization.objects.get(id=event.organization_id)

    # Every credit line on an InvoiceIssued-sourced entry IS a
    # revenue line, by construction — posting_engine.resolve()'s own
    # InvoiceIssued rule always shapes it Dr AR (debit) / Cr Service
    # + Cr Parts Revenue (credits). Filtering for credits here
    # naturally excludes the AR debit line without hardcoding
    # 4001/4002 and risking drift from what was really posted.
    revenue_lines = [line for line in original.lines.all() if line.credit_amount > 0]
    total_revenue = sum((line.credit_amount for line in revenue_lines), Decimal("0"))

    if total_revenue <= Decimal("0"):
        # Structurally shouldn't happen — an InvoiceIssued entry
        # always has at least one revenue credit line, since
        # JournalEntry.post() itself refuses a zero-total posting —
        # checked anyway rather than silently posting nothing for a
        # real refund.
        return None

    lines = [
        {"account": line.account, "debit": line.credit_amount, "credit": None}
        for line in revenue_lines
    ] + [
        {
            "account": Account.resolve(organization, cash_or_bank_account_code(event.method)),
            "debit": None,
            "credit": total_revenue,
        },
    ]

    return JournalEntry.post(
        organization=organization,
        posting_date=_safe_posting_date(event),
        source=JournalEntry.Source.DOMAIN_EVENT,
        event_type=event.event_type,
        reference_event_id=event.event_id,
        memo=f"Refund of {original.entry_number} — invoice refunded",
        # 6 Sep 2026 — real audit-trail fix. See module docstring —
        # event.refunded_by is now genuinely populated, threaded all
        # the way from Refund.record()'s own real refunded_by
        # parameter.
        created_by=_resolve_actor(getattr(event, "refunded_by", None)),
        lines=lines,
    )
