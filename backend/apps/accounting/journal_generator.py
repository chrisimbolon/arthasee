# =============================================================================
# === backend/apps/accounting/journal_generator.py ===
# =============================================================================
"""
Arthasee — Journal Generator

Turns a posting_engine.resolve(event) result into a real, posted
JournalEntry for one event's organization — the layer that actually
touches the database, resolving account CODES into real Account rows
scoped to the event's own organization_id.

Idempotent by construction: if a JournalEntry already exists for this
event's event_id (reference_event_id), posting is skipped entirely —
EventHandler.handle()'s own docstring already calls out that handlers
must be idempotent wherever realistically possible; this is where
that promise is actually kept for accounting postings.
"""
from apps.accounting import posting_engine
from apps.accounting.models import Account, JournalEntry
from apps.organizations.models import Organization
from django.utils import timezone


def post_for_event(event) -> JournalEntry | None:
    """
    Returns the created JournalEntry, or None if there was nothing to
    post (an empty posting_engine.resolve() result — e.g. a
    labor-only WorkOrderCompleted with amount=0) or if this event was
    already posted before (idempotency guard above).

    Deliberately does not catch or wrap any exception raised here
    (e.g. the ValueError Account.resolve() raises if the Chart of
    Accounts hasn't been seeded for this organization).
    apps.core.events.dispatcher already catches per-handler
    exceptions, marks the Outbox row FAILED with the error captured,
    and logs it — swallowing the error here would just hide it one
    layer earlier for no benefit.
    """
    if JournalEntry.objects.filter(reference_event_id=event.event_id).exists():
        return None

    resolved = posting_engine.resolve(event)
    if not resolved["lines"]:
        return None

    organization = Organization.objects.get(id=event.organization_id)
    lines = [
        {
            "account": Account.resolve(organization, entry["account_code"]),
            "debit":  entry["amount"] if entry["side"] == "debit" else None,
            "credit": entry["amount"] if entry["side"] == "credit" else None,
        }
        for entry in resolved["lines"]
    ]

    # 28 Aug 2026 — real bug found live: occurred_at is WHEN the
    # event was published (system/server time), not necessarily the
    # real business date a transaction represents — most events
    # coincide (fired the instant the action happens), but any event
    # sourced from a user-chosen date (OperatingExpense's own
    # paid_at, confirmed live to diverge from "now") would silently
    # post to the WRONG accounting period, exactly as if the real
    # date had never been entered at all. transaction_date is a new,
    # OPTIONAL, generic field name any event can freeze its own real
    # business date into (same "frozen event payload" discipline
    # PurchaseReturned's own debit_account_code already established)
    # — falls back to occurred_at for every event that doesn't set
    # it, so this is fully backward compatible with every existing
    # event class.
    #
    # 5 Sep 2026 — real, SECOND bug found via a design-review trace
    # (Sansan's own "midnight boundary" question), not a live
    # incident: the fallback branch called occurred_at.date()
    # directly — under USE_TZ=True (confirmed: this project's own
    # TIME_ZONE is "Asia/Jakarta", UTC+7), occurred_at is stored and
    # compared as a UTC-aware datetime, so .date() extracts the UTC
    # CALENDAR DATE, not the shop's real local one. A transaction
    # occurring between local midnight and 7am would silently
    # extract the PREVIOUS day's date — exactly the kind of
    # off-by-one-period bug a real reconciliation near a month
    # boundary would surface as a mismatch nobody could explain.
    # timezone.localtime() is the correct, purpose-built Django
    # utility for converting a stored UTC-aware datetime back to the
    # project's configured local zone before extracting a plain
    # date — fixes this for EVERY event type that falls through to
    # this branch, not just the ones with their own transaction_date
    # (WorkOrderCompleted/GoodsReceived/InvoiceIssued/PartConsumed
    # among them) — a real, separate, scoped audit of whether any of
    # those genuinely need their own frozen transaction_date field
    # too, not silently assumed here.
    # timezone.is_aware() guard: timezone.localtime() requires an
    # AWARE datetime and raises ValueError on a naive one. occurred_at
    # is expected to always be aware (populated via timezone.now()
    # under USE_TZ=True), but this defensively falls back to the raw
    # date rather than crash if that assumption is ever wrong for some
    # caller this review didn't see.
    if getattr(event, "transaction_date", None):
        posting_date = event.transaction_date
    elif timezone.is_aware(event.occurred_at):
        posting_date = timezone.localtime(event.occurred_at).date()
    else:
        posting_date = event.occurred_at.date()

    return JournalEntry.post(
        organization=organization,
        posting_date=posting_date,
        source=JournalEntry.Source.DOMAIN_EVENT,
        event_type=event.event_type,
        reference_event_id=event.event_id,
        memo=resolved["memo"],
        lines=lines,
    )
