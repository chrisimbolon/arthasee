# =============================================================================
# === backend/apps/customers/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import TrackingLink


class TrackingLinkSerializer(serializers.ModelSerializer):
    """Internal-facing only — used when Made/SA generates or lists
    links for a WorkOrder. Never touches the public endpoint."""
    class Meta:
        model  = TrackingLink
        fields = ["id", "work_order", "token", "is_revoked", "last_viewed_at", "view_count", "created_at"]
        read_only_fields = ["id", "token", "last_viewed_at", "view_count", "created_at"]


class PublicStageSerializer(serializers.Serializer):
    """
    Chris's own explicit Fase 2 v1 scope: stage name + completion
    status + timestamps only — no job-line-level detail (that's
    Sansan's mockup's granularity, not what Made's signed note asked
    for), no photos.
    """
    name         = serializers.CharField()
    status       = serializers.SerializerMethodField()
    started_at   = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)

    def get_status(self, stage):
        if stage.completed_at:
            return "Selesai"
        if stage.started_at:
            return "Sedang Berjalan"
        return "Menunggu"


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
    invoice            = PublicInvoiceSerializer(allow_null=True)
