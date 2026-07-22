# =============================================================================
# === backend/apps/inventory/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import Part, PartUsage, StockAdjustment


def _user_org_ids(request):
    """
    Same helper as apps.service.serializers' own copy — kept as a
    small local duplicate rather than a cross-app import. This one
    function is genuinely tiny and app-agnostic; importing it from
    apps.service would create a real dependency in the direction we
    just spent effort removing (inventory should not need to know
    apps.service exists to answer "what orgs can this user see").
    """
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class PartSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Part
        fields = ["id", "name", "sku", "unit", "current_stock", "unit_price", "created_at", "updated_at"]
        # current_stock is intentionally NOT writable here — it only
        # ever changes through PartUsage or StockAdjustment, both of
        # which go through the atomic F() update in models.py.
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
        return obj.part.current_stock

    def validate(self, data):
        """
        Deliberately a WARNING, not a hard block — see the module
        docstring in models.py for the real-world reasoning.
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
