# =============================================================================
# === backend/apps/workorders/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import (Mechanic, WorkOrder, WorkOrderJobLine,
                     WorkOrderMaterialLine, WorkOrderStage)


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class MechanicSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Mechanic
        fields = ["id", "name", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class WorkOrderJobLineSerializer(serializers.ModelSerializer):
    class Meta:
        model  = WorkOrderJobLine
        fields = ["id", "work_order", "stage", "description", "is_done", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_stage(self, stage):
        """
        A job line's stage must belong to the SAME WorkOrder it's
        being created/assigned on — without this, nothing stops a
        stray cross-WorkOrder (or even cross-org) stage id from
        silently attaching a job line to a completely unrelated
        repair's stage. self.initial_data["work_order"] is reliable
        here because both call sites (WorkOrderJobLineListView.post()
        and the assign-stage endpoint) always set it in the payload
        before this serializer ever validates.
        """
        if stage is None:
            return stage
        work_order_id = self.initial_data.get("work_order")
        if work_order_id and str(stage.work_order_id) != str(work_order_id):
            raise serializers.ValidationError("Tahap tidak sesuai dengan work order ini.")
        return stage


class WorkOrderMaterialLineSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    unit      = serializers.CharField(source="part.unit", read_only=True)
    subtotal  = serializers.SerializerMethodField()

    class Meta:
        model  = WorkOrderMaterialLine
        fields = [
            "id", "work_order", "part", "part_name", "unit",
            "quantity", "unit_price_at_time", "subtotal", "created_at",
        ]
        read_only_fields = ["id", "part_name", "unit", "unit_price_at_time", "subtotal", "created_at"]

    def get_subtotal(self, obj):
        return obj.quantity * obj.unit_price_at_time

    def validate_part(self, part):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return part
        if part.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Part tidak ditemukan.")
        return part


class WorkOrderStageSerializer(serializers.ModelSerializer):
    # Nested read-only — a stage's own view of exactly which job
    # lines currently belong to it. WorkOrderJobLine's own flat list
    # (on WorkOrderSerializer) stays the full, ungrouped set — this
    # is purely a convenience so the frontend doesn't need to
    # cross-reference two separate lists by hand to render one
    # stage's card.
    job_lines      = WorkOrderJobLineSerializer(many=True, read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.name", read_only=True, default=None)
    is_overdue     = serializers.BooleanField(read_only=True)

    class Meta:
        model  = WorkOrderStage
        fields = [
            "id", "work_order", "name", "sequence",
            "assigned_to", "assigned_to_name", "expected_duration_hours",
            "started_at", "completed_at", "is_overdue", "job_lines", "created_at",
        ]
        # started_at/completed_at are deliberately read-only here —
        # they only ever move through start()/complete(), never a
        # direct field write, same discipline as WorkOrder.status
        # never being settable through a plain PUT. assigned_to and
        # expected_duration_hours ARE writable — see
        # WorkOrderStageDetailView.put()'s own allowed-fields list.
        read_only_fields = ["id", "assigned_to_name", "started_at", "completed_at", "is_overdue", "job_lines", "created_at"]

    def validate_assigned_to(self, mechanic):
        request = self.context.get("request")
        if mechanic is None or request is None or request.user.role == "super_admin":
            return mechanic
        if mechanic.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Mekanik tidak ditemukan.")
        return mechanic


class WorkOrderSerializer(serializers.ModelSerializer):
    job_lines       = WorkOrderJobLineSerializer(many=True, read_only=True)
    material_lines   = WorkOrderMaterialLineSerializer(many=True, read_only=True)
    stages           = WorkOrderStageSerializer(many=True, read_only=True)
    vehicle_plate    = serializers.CharField(source="vehicle.plate_number", read_only=True)
    customer_name    = serializers.CharField(source="vehicle.customer.name", read_only=True)
    created_by_name  = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    is_overdue       = serializers.BooleanField(read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.name", read_only=True, default=None)

    class Meta:
        model  = WorkOrder
        fields = [
            "id", "vehicle", "vehicle_plate", "customer_name",
            "number", "sequence_number", "status",
            "odometer_km_intake", "received_by", "notes", "work_started_at", "is_overdue",
            "assigned_to", "assigned_to_name",
            "service_record", "job_lines", "material_lines", "stages",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "vehicle_plate", "customer_name", "number", "sequence_number", "status",
            "work_started_at", "is_overdue", "assigned_to_name",
            "service_record", "job_lines", "material_lines", "stages",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def validate_vehicle(self, vehicle):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        if vehicle.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle

    def validate_assigned_to(self, mechanic):
        if mechanic is None:
            return mechanic
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return mechanic
        if mechanic.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Mekanik tidak ditemukan.")
        return mechanic


class WorkOrderListSerializer(WorkOrderSerializer):
    """Lighter version for list views — no nested lines, same
    reasoning as VehicleListSerializer's own trimmed-down shape."""
    class Meta(WorkOrderSerializer.Meta):
        fields = [f for f in WorkOrderSerializer.Meta.fields if f not in ("job_lines", "material_lines", "stages")]
