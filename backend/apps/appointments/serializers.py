# =============================================================================
# === backend/apps/appointments/serializers.py ===
# =============================================================================
from datetime import date

from rest_framework import serializers


class AppointmentCreateSerializer(serializers.Serializer):
    """
    Light by design — Chris's own confirmed scope: date, vehicle,
    free-text notes only. No service-item selection in v1.
    """
    vehicle_id      = serializers.UUIDField()
    requested_date  = serializers.DateField()
    notes           = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_requested_date(self, value):
        if value < date.today():
            raise serializers.ValidationError("Tanggal tidak boleh di masa lalu.")
        return value


class AppointmentSerializer(serializers.Serializer):
    """
    Deliberately whitelist-only — same discipline as
    apps.customers.serializers.PublicTrackingSerializer: a field
    added to Appointment/Vehicle later can never silently leak here
    just by existing on the model.
    """
    id              = serializers.CharField()
    requested_date  = serializers.DateField()
    notes           = serializers.CharField()
    status          = serializers.CharField()
    vehicle_plate   = serializers.CharField(source="vehicle.plate_number")
    vehicle_model   = serializers.CharField(source="vehicle.model")
    created_at      = serializers.DateTimeField()


class AppointmentAvailabilityDaySerializer(serializers.Serializer):
    date      = serializers.DateField()
    booked    = serializers.IntegerField()
    capacity  = serializers.IntegerField()
    available = serializers.BooleanField()
