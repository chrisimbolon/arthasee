# =============================================================================
# === backend/apps/core/models.py
# =============================================================================
"""
Arthasee — Core

Same tenant-scoping pattern proven across every DevelopIndo sprint:
one abstract base every real model inherits from, one hook point for
models that derive their org from a relation instead of expecting
the caller to set it explicitly.
"""
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


class TenantScopedModel(models.Model):
    """
    Abstract base for every model that belongs to exactly one
    Organization. Paired with TenantScopedAPIView (see views.py) —
    together they're the only two places tenant isolation actually
    gets enforced, which is deliberate: one mechanism, reused
    everywhere, rather than each view reinventing its own scoping.

    _resolve_organization() is the override point for models that
    derive their organization from a related object rather than
    being set explicitly by the caller — e.g. a ServiceRecord derives
    its org from its own Vehicle, the same way DevelopIndo's
    CommissionTier derived its org from its own CommissionPolicy.
    """
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE,
    )

    class Meta:
        abstract = True

    def _resolve_organization(self):
        return None

    def save(self, *args, **kwargs):
        if self.organization_id is None:
            resolved = self._resolve_organization()
            if resolved is not None:
                self.organization = resolved
        super().save(*args, **kwargs)


class Outbox(TenantScopedModel):
    """
    One durable row per published DomainEvent — the "Transactional
    Safety" / "reliable delivery" guarantee from the event-bus
    architecture (see apps/core/events/bus.py, apps/core/events/
    dispatcher.py). Written in the SAME transaction as whatever
    business action produced the event, so the event's existence is
    never dependent on any handler actually succeeding, or even
    existing yet.

    Deliberately defined here rather than in apps/core/events/
    outbox.py, even though that's this concept's real conceptual
    home: Django only auto-discovers models that live in (or are
    imported by) <app>.models at startup — defining it in the events
    subpackage instead would mean it silently never gets registered
    unless something else happens to import that module first. See
    apps/core/events/outbox.py for the thin re-export that keeps the
    import path the roadmap specifies (apps.core.events.outbox.Outbox)
    working anyway.

    organization is always set explicitly by EventBus.publish() (every
    DomainEvent already carries organization_id) — _resolve_organization
    is never invoked here, same as Part/Customer elsewhere.
    """
    class Status(models.TextChoices):
        PENDING   = "PENDING", "Pending"
        PROCESSED = "PROCESSED", "Processed"
        FAILED    = "FAILED", "Failed"

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id   = models.UUIDField(unique=True, editable=False, verbose_name="Event ID")
    event_type = models.CharField(max_length=100, db_index=True, verbose_name="Tipe Event")
    # DjangoJSONEncoder handles Decimal/UUID/datetime out of the box
    # (encodes them as strings) — exactly the payload shapes real
    # domain events will carry from Sprint 2 onward (amounts,
    # quantities, related-object ids), no custom encoder needed.
    payload = models.JSONField(encoder=DjangoJSONEncoder, verbose_name="Payload")
    occurred_at = models.DateTimeField(verbose_name="Waktu Kejadian")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        db_index=True, verbose_name="Status",
    )
    attempts   = models.PositiveIntegerField(default=0, verbose_name="Percobaan")
    last_error = models.TextField(blank=True, default="", verbose_name="Error Terakhir")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="Waktu Diproses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Outbox Event"
        verbose_name_plural  = "Outbox Events"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.status}) — {self.event_id}"

    def mark_processed(self):
        self.status = self.Status.PROCESSED
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "processed_at"])

    def mark_failed(self, error_message: str):
        # F()-expression increment, not read-modify-write — same
        # reasoning as PartUsage.save()'s own stock deduction: avoids
        # a race if a retry path and a fresh dispatch somehow overlap.
        self.attempts = models.F("attempts") + 1
        self.status = self.Status.FAILED
        self.last_error = error_message
        self.save(update_fields=["status", "attempts", "last_error"])
