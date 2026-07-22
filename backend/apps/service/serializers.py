# =============================================================================
# === backend/apps/service/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import (Customer, Part, PartUsage, ServiceRecord, StockAdjustment,
                     Vehicle)


def _user_org_ids(request):
    """
    Shared helper — every cross-tenant validate_* method below needs
    exactly this same lookup. Pulled out once rather than
    re-duplicated per serializer, same instinct as not re-inventing
    tenant scoping per view.
    """
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class CustomerSerializer(serializers.ModelSerializer):
    vehicle_count = serializers.IntegerField(source="vehicles.count", read_only=True)

    class Meta:
        model  = Customer
        fields = ["id", "name", "phone", "stnk_name", "vehicle_count", "created_at", "updated_at"]
        read_only_fields = ["id", "vehicle_count", "created_at", "updated_at"]


class ServiceRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    part_usages      = serializers.SerializerMethodField()

    class Meta:
        model  = ServiceRecord
        fields = [
            "id", "vehicle", "service_date", "odometer_km",
            "issue_description", "parts_replaced", "notes", "part_usages",
            "created_by", "created_by_name", "created_at",
        ]
        # Append-only, same as every audit-style record elsewhere —
        # nothing here is editable after creation, including via API.
        read_only_fields = ["id", "created_by", "created_by_name", "created_at", "part_usages"]

    def get_part_usages(self, obj):
        # Deliberately not nesting the full PartUsageSerializer here
        # to avoid a second round of cross-tenant validation context
        # plumbing for a read-only nested list — this is a lighter,
        # display-only shape.
        return [
            {
                "id": pu.id, "part": pu.part_id, "part_name": pu.part.name,
                "quantity": pu.quantity, "unit": pu.part.unit,
                "unit_price_at_time": pu.unit_price_at_time,
            }
            for pu in obj.part_usages.select_related("part").all()
        ]

    def validate_vehicle(self, vehicle):
        """Same cross-tenant guard as VehicleSerializer.validate_customer
        — a vehicle id from another shop must never be accepted here."""
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return vehicle
        if vehicle.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Kendaraan tidak ditemukan.")
        return vehicle


class VehicleSerializer(serializers.ModelSerializer):
    customer_name              = serializers.CharField(source="customer.name", read_only=True)
    is_due_for_service          = serializers.BooleanField(read_only=True)
    is_registration_expiring_soon = serializers.BooleanField(read_only=True)
    service_records             = ServiceRecordSerializer(many=True, read_only=True)

    class Meta:
        model  = Vehicle
        fields = [
            "id", "customer", "customer_name",
            "plate_number", "manufacture_year", "vehicle_type", "body_style", "model",
            "chassis_number", "engine_number", "bpkb_number", "color", "registration_expiry",
            "current_odometer_km", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "is_registration_expiring_soon", "service_records",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "customer_name", "last_service_date", "last_service_odometer_km",
            "is_due_for_service", "is_registration_expiring_soon", "service_records",
            "created_at", "updated_at",
        ]

    def validate_customer(self, customer):
        """
        Without this, a request could pass any customer id, including
        one belonging to a completely different shop — Vehicle would
        then silently resolve to THAT shop's organization via
        _resolve_organization(), a real cross-tenant leak. Same class
        of check DevelopIndo's validate_project() did for Units.
        """
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return customer
        if customer.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Pelanggan tidak ditemukan.")
        return customer


class VehicleListSerializer(VehicleSerializer):
    """
    Lighter version for list views — no nested service_records, so
    listing 50 vehicles doesn't drag along every historical service
    record for each one.
    """
    class Meta(VehicleSerializer.Meta):
        fields = [f for f in VehicleSerializer.Meta.fields if f != "service_records"]


# =============================================================================
# === Sprint 1: Inventory ===
# =============================================================================

class PartSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Part
        fields = ["id", "name", "sku", "unit", "current_stock", "unit_price", "created_at", "updated_at"]
        # current_stock is intentionally NOT writable here — it only
        # ever changes through PartUsage or StockAdjustment, both of
        # which go through the atomic F() update in models.py.
        # Allowing a direct PUT to current_stock would create a second,
        # inconsistent path to the same value with no audit trail.
        read_only_fields = ["id", "current_stock", "created_at", "updated_at"]


class PartUsageSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    unit      = serializers.CharField(source="part.unit", read_only=True)
    resulting_stock = serializers.SerializerMethodField()

    class Meta:
        model  = PartUsage
        fields = [
            "id", "service_record", "part", "part_name", "unit",
            "quantity", "unit_price_at_time", "resulting_stock", "created_at",
        ]
        read_only_fields = ["id", "part_name", "unit", "unit_price_at_time", "resulting_stock", "created_at"]

    def get_resulting_stock(self, obj):
        # Informational only, computed post-save — surfaces the same
        # number Made's note described ("20-4=16") directly in the
        # API response, so the frontend can show it without a second
        # request.
        return obj.part.current_stock

    def validate(self, data):
        """
        Deliberately a WARNING, not a hard block: real shops sometimes
        use a part before the system has caught up (physical stock
        arrived and got used same-day, adjustment not logged yet).
        Blocking that outright would stop a mechanic from recording
        real work over a data-entry timing issue — worse than letting
        stock go visibly negative, which is just as informative and
        never silently wrong. This is a judgment call, flagged in the
        roadmap doc as worth revisiting with Made directly.
        """
        part = data.get("part") or getattr(self.instance, "part", None)
        quantity = data.get("quantity")
        if part and quantity is not None and part.current_stock < quantity:
            self.context.setdefault("warnings", []).append(
                f"Stok '{part.name}' akan menjadi negatif "
                f"({part.current_stock} - {quantity} = {part.current_stock - quantity})."
            )
        return data

    def validate_part(self, part):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return part
        if part.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Part tidak ditemukan.")
        return part

    def validate_service_record(self, service_record):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return service_record
        if service_record.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Catatan servis tidak ditemukan.")
        return service_record


class StockAdjustmentSerializer(serializers.ModelSerializer):
    part_name = serializers.CharField(source="part.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    resulting_stock = serializers.SerializerMethodField()

    class Meta:
        model  = StockAdjustment
        fields = [
            "id", "part", "part_name", "quantity_change", "reason", "notes",
            "created_by", "created_by_name", "resulting_stock", "created_at",
        ]
        read_only_fields = ["id", "part_name", "created_by", "created_by_name", "resulting_stock", "created_at"]

    def get_resulting_stock(self, obj):
        return obj.part.current_stock

    def validate_part(self, part):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return part
        if part.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Part tidak ditemukan.")
        return part
