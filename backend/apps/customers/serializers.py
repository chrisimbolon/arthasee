# =============================================================================
# === backend/apps/customers/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import MagicLinkToken, TrackingLink


class TrackingLinkSerializer(serializers.ModelSerializer):
    """Internal-facing only — used when Made/SA generates or lists
    links for a WorkOrder. Never touches the public endpoint."""
    class Meta:
        model  = TrackingLink
        fields = ["id", "work_order", "token", "is_revoked", "last_viewed_at", "view_count", "created_at"]
        read_only_fields = ["id", "token", "last_viewed_at", "view_count", "created_at"]


class PublicJobLineSerializer(serializers.Serializer):
    """
    Made's own confirmed handwritten note, 4 Aug: "Pekerjaan
    bertahap: jam mulai – jam selesai" — multi-step work needs real
    per-step start/end timing. Chris's own explicit scope call, same
    day: this now goes on the CUSTOMER-facing timeline too, not just
    internal — a badly-damaged car's owner genuinely wants to see
    "bongkar done, parts on order now," not just an overall stage
    status. This is a deliberate widening of Fase 2 v1's original
    "stage-level only" scope (see PublicStageSerializer's own older
    comment) — a real, separate decision from Made's note itself, not
    inferred from it.
    """
    description  = serializers.CharField()
    status       = serializers.CharField()
    started_at   = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class PublicStageSerializer(serializers.Serializer):
    """
    Stage name + completion status + timestamps, now with each
    stage's own real job lines nested underneath (see
    PublicJobLineSerializer's own docstring for why that scope
    changed, 4 Aug). status is a plain field, not a
    SerializerMethodField — payload.py computes it once, the same way
    for stages and job lines both, rather than duplicating that
    three-state logic in two places.
    """
    name         = serializers.CharField()
    status       = serializers.CharField()
    started_at   = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    job_lines    = PublicJobLineSerializer(many=True)


class PublicInvoiceSerializer(serializers.Serializer):
    """
    Only ever included by the view once WorkOrder.status == "DONE"
    and a real Invoice exists — see PublicTrackingView.get(). Made's
    own confirmed reason for mechanic attribution here: "Di invoice
    muncul sampai mekanik" — the same mechanic_name_snapshot already
    proven internally (item 22, shipped 31 Jul), just surfaced to the
    customer's own read-only view.
    """
    number                 = serializers.CharField()
    mechanic_name_snapshot = serializers.CharField()
    total                  = serializers.DecimalField(max_digits=14, decimal_places=2)
    status                 = serializers.CharField()


class PublicTrackingSerializer(serializers.Serializer):
    """
    The entire public payload — deliberately whitelist-only, built by
    hand from a plain dict in the view rather than serializing a
    WorkOrder/Vehicle model instance directly. That's not a style
    choice: it means a field added to WorkOrder or Vehicle later can
    never silently leak onto this public, unauthenticated endpoint
    just by existing on the model — someone has to deliberately add
    it here first.
    """
    work_order_number = serializers.CharField()
    status             = serializers.CharField()
    vehicle_plate      = serializers.CharField()
    vehicle_model      = serializers.CharField()
    mechanic_name      = serializers.CharField(allow_null=True)
    stages             = PublicStageSerializer(many=True)
    # Mirrors the internal page's own "Pekerjaan Lain (Tanpa Tahap)"
    # section — routine, unstaged work (an oil change on its own, not
    # part of a multi-step overhaul) still has real timing now too,
    # shown the same honest way as everything staged.
    unstaged_job_lines = PublicJobLineSerializer(many=True)
    invoice            = PublicInvoiceSerializer(allow_null=True)


class CustomerWorkOrderSummarySerializer(serializers.Serializer):
    """
    Fase 2.5 — the dashboard list view (active + history tabs), one
    row per WorkOrder. Deliberately lighter than
    PublicTrackingSerializer — no stage breakdown, no invoice detail;
    those live behind the real detail endpoint
    (CustomerWorkOrderDetailView, which reuses the exact same
    build_work_order_tracking_payload() as the token-link path). This
    is just enough to render a list and let the customer pick one.
    """
    id                 = serializers.CharField()
    work_order_number  = serializers.CharField()
    status             = serializers.CharField()
    vehicle_plate      = serializers.CharField()
    vehicle_model      = serializers.CharField()
    created_at         = serializers.DateTimeField()


class MagicLinkRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class MagicLinkVerifySerializer(serializers.Serializer):
    token = serializers.CharField()


class CustomerSessionSerializer(serializers.Serializer):
    """
    What the frontend actually needs after a successful magic-link
    verify — an access token, plus enough of the Customer's own
    identity to render "Hi, {name}" without a second round-trip.
    Deliberately narrow, same whitelist discipline as everything else
    customer-facing — no organization id, no internal Customer fields
    beyond name/email.
    """
    access = serializers.CharField()
    name   = serializers.CharField()
    email  = serializers.EmailField()
