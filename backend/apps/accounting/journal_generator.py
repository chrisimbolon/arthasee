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


def post_for_event(event) -> JournalEntry | None:
    """
    Returns the created JournalEntry, or None if there was nothing to
    post (an empty posting_engine.resolve() result — e.g. a
    labor-only WorkOrderCompleted with amount=0) or if this event was
    already posted before (idempotency guard above).

    Deliberately does not catch or wrap any exception raised here
    (e.g. Account.DoesNotExist if the Chart of Accounts hasn't been
    seeded for this organization — see _get_account's own clearer
    error message for that specific case). apps.core.events.dispatcher
    already catches per-handler exceptions, marks the Outbox row
    FAILED with the error captured, and logs it — swallowing the
    error here would just hide it one layer earlier for no benefit.
    """
    if JournalEntry.objects.filter(reference_event_id=event.event_id).exists():
        return None

    resolved = posting_engine.resolve(event)
    if not resolved["lines"]:
        return None

    organization = Organization.objects.get(id=event.organization_id)
    lines = [
        {
            "account": _get_account(organization, entry["account_code"]),
            "debit":  entry["amount"] if entry["side"] == "debit" else None,
            "credit": entry["amount"] if entry["side"] == "credit" else None,
        }
        for entry in resolved["lines"]
    ]

    return JournalEntry.post(
        organization=organization,
        posting_date=event.occurred_at.date(),
        source=JournalEntry.Source.DOMAIN_EVENT,
        event_type=event.event_type,
        reference_event_id=event.event_id,
        memo=resolved["memo"],
        lines=lines,
    )


def _get_account(organization, code):
    try:
        return Account.objects.get(organization=organization, code=code)
    except Account.DoesNotExist as exc:
        raise ValueError(
            f"No Account with code={code!r} found for organization "
            f"{organization.name!r} — has the Chart of Accounts been "
            f"seeded (python manage.py seed_coa)?"
        ) from exc
