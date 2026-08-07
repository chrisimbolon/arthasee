# =============================================================================
# === backend/apps/core/events/base.py ===
# =============================================================================
"""
Arthasee — Core Event Bus: Envelope & Serialization Utilities

One canonical way to turn a DomainEvent into a plain dict — used when
writing the Outbox row (see outbox.py), when logging a dispatch
failure, and later (Phase 4, Task 4.2) by the Audit Log Viewer, which
will want the exact same shape a handler saw rather than reaching
into Outbox.payload and reconstructing it by hand.
"""
from __future__ import annotations

from typing import Any

from apps.core.events.interfaces import DomainEvent


def to_envelope(event: DomainEvent) -> dict[str, Any]:
    """
    Canonical dict representation of one DomainEvent instance.

    Deliberately mirrors the Outbox model's own columns 1:1
    (event_type/event_id/occurred_at are real Outbox columns;
    "payload" is what goes in Outbox.payload) — one source of truth
    for the shape, not two conventions that could drift apart.
    """
    return {
        "event_type": event.event_type,
        "event_id": str(event.event_id),
        "organization_id": str(event.organization_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload(),
    }
