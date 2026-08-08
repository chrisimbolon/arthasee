# =============================================================================
# === backend/apps/accounting/handlers.py ===
# =============================================================================
"""
Arthasee — Accounting Event Handler

Subscribes to every domain event the posting engine knows how to
post. One handler, four event types — the real logic all lives in
posting_engine.py/journal_generator.py; this class is intentionally
thin, matching EventHandler's own "one handler = one bounded concern"
framing. The concern here is "react to domain events by posting
journal entries" — one concern, even though it spans four event
types, not four unrelated ones.
"""
from apps.core.events.handlers import EventHandler
from apps.core.events.interfaces import DomainEvent

from . import journal_generator


class AccountingEventHandler(EventHandler):
    handles = ("PartConsumed", "WorkOrderCompleted", "InvoiceIssued", "PaymentReceived")

    def handle(self, event: DomainEvent) -> None:
        journal_generator.post_for_event(event)
