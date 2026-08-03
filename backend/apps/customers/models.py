# =============================================================================
# === backend/apps/customers/models.py ===
# =============================================================================
"""
Arthasee — Customer Tracking Links (Fase 2, confirmed with Made/
Chris, 2 Aug)

A single, revocable, unguessable link Made can paste into WhatsApp so
a customer or institutional client can check a real WorkOrder's
progress with zero login — deliberately NOT tied to Customer.email or
any account/login flow. Chris's own explicit call, and the reason
this exists at all: an unverified email-match flow (type an email,
see all Work Orders for that Customer.email) would let anyone who
knows or guesses a customer's email see their entire service history
— for an institutional client like Polresta Batanghari, a contact
email is realistically public/guessable. Full customer accounts
(email + magic-link verification, a real "my vehicles" list for fleet
clients) are parked for Fase 2.5 specifically because that
verification step doesn't exist yet — this app deliberately does not
attempt it.

Fase 2 v1 scope, confirmed: stage names + completion status + a
timeline (WorkOrderStage.started_at/completed_at, already real data —
nothing new modeled there), assigned mechanic, and — only once a
WorkOrder is DONE and a real Invoice exists — the invoice number,
mechanic attribution, and total. Deliberately excluded, matching
Made's own signed Fase 2 note ("tidak perlu foto") and Chris's own
scope calls: no photos, no mechanic chat, no customer-side approve/
reject, no contract/termin financials (institutional clients pay via
TerminPeriod schedules, not a flat invoice — this view has no
business showing that), no fabricated completion percentage.
"""
import secrets
import uuid

from apps.core.models import TenantScopedModel
from django.db import models
from django.utils import timezone


def _generate_token():
    # 256-bit random token — the token itself is the only credential
    # on the public endpoint, so this needs real entropy, not a
    # short/guessable ID. token_urlsafe(32) is the same magnitude of
    # randomness already trusted implicitly by UUID4 primary keys
    # elsewhere in this project.
    return secrets.token_urlsafe(32)


class TrackingLink(TenantScopedModel):
    """
    Deliberately its own model, not `WorkOrder.id` reused as a public
    identifier directly — a separate random token means the real
    internal WorkOrder UUID is never exposed publicly, and a single
    link can be individually revoked (sent to the wrong number,
    leaked, contract ended) without touching the WorkOrder itself or
    invalidating any other link for the same job.

    view_count/last_viewed_at exist so Made has a real, honest signal
    of whether a client has actually opened a link he sent — not
    vanity metrics, closes a genuine "did they even see it" gap for a
    shop owner managing client communication over WhatsApp by hand.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    work_order = models.ForeignKey(
        "workorders.WorkOrder", on_delete=models.CASCADE, related_name="tracking_links",
        verbose_name="Work Order",
    )
    token      = models.CharField(max_length=64, unique=True, editable=False, default=_generate_token, db_index=True)
    is_revoked = models.BooleanField(default=False, verbose_name="Dicabut")
    created_by = models.ForeignKey(
        "authentication.CustomUser", on_delete=models.SET_NULL, null=True, blank=True,
    )
    last_viewed_at = models.DateTimeField(null=True, blank=True, verbose_name="Terakhir Dilihat")
    view_count     = models.PositiveIntegerField(default=0, verbose_name="Jumlah Dilihat")
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Tracking Link"
        verbose_name_plural  = "Tracking Links"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"Tracking link for WO {self.work_order.number}"

    def _resolve_organization(self):
        return self.work_order.organization

    def record_view(self):
        """
        Called by the public tracking endpoint on every real fetch —
        a genuine DB write, not just data returned to the caller, so
        this stays an honest signal rather than something that only
        updates when someone happens to look at it internally.
        """
        self.view_count += 1
        self.last_viewed_at = timezone.now()
        self.save(update_fields=["view_count", "last_viewed_at"])


class MagicLinkToken(TenantScopedModel):
    """
    Fase 2.5 (confirmed with Made/Chris, 3 Aug) — real customer
    accounts, magic-link login. A customer types their email, gets a
    single-use link, clicks it, they're in — no password to set,
    reset, or leak. Chris's own explicit call over password auth:
    "cleaner, eliminates password resets, fits the low-friction feel
    of the app."

    Deliberately its own model, same reasoning as TrackingLink's own
    docstring — a real, single-use, short-lived, revocable-by-expiry
    credential, not a bare field on Customer. 15-minute expiry,
    single-use (used_at set the moment it's redeemed) — a real magic
    link left sitting in an inbox for days must not still work.

    NOT yet wired to a real email provider — Resend/SendGrid
    integration is the other, deliberately deferred half of Fase 2.5
    (Chris's own explicit call, 3 Aug: ship everything buildable now,
    stub only the actual send). See
    CustomerMagicLinkRequestView.post() in views.py for exactly where
    that real send call needs to go once a provider is chosen — the
    token itself, the whole verify/login flow, and the customer
    dashboard behind it are all real and fully working today.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer    = models.ForeignKey(
        "service.Customer", on_delete=models.CASCADE, related_name="magic_link_tokens",
        verbose_name="Pelanggan",
    )
    token       = models.CharField(max_length=64, unique=True, editable=False, default=_generate_token, db_index=True)
    expires_at  = models.DateTimeField(verbose_name="Kadaluarsa")
    used_at     = models.DateTimeField(null=True, blank=True, verbose_name="Digunakan Pada")
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = "Magic Link Token"
        verbose_name_plural  = "Magic Link Tokens"
        ordering             = ["-created_at"]

    def __str__(self):
        return f"Magic link for {self.customer.name}"

    def _resolve_organization(self):
        return self.customer.organization

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])
