# =============================================================================
# === backend/apps/core/events/outbox.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Outbox

The real Outbox model class lives in apps/core/models.py, not here —
see that file's own docstring on Outbox for exactly why (Django's
model auto-discovery only walks <app>.models at startup; a model
defined only in this subpackage would never get registered unless
something else happened to import it first).

This module exists purely so the import path documented in the
roadmap keeps working:

    from apps.core.events.outbox import Outbox

Bus/dispatcher code in this package should still prefer importing
from here rather than reaching into apps.core.models directly — it
keeps every "events" concept importable from one consistent place,
even though the underlying class is physically defined elsewhere for
Django's sake.
"""
from apps.core.models import Outbox  # noqa: F401
