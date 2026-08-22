# =============================================================================
# === backend/apps/inventory/serializers.py ===
# =============================================================================
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import (Part, PartUsage, StockAdjustment, StockOpnameLineItem,
                     StockOpnameSession)


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
        fields = [
            "id", "name", "sku", "unit", "current_stock", "unit_price", "minimum_stock",
            "item_type", "vehicle_brand", "fluid_brand", "viscosity_grade", "reorder_cadence",
            "created_at", "updated_at",
        ]
        # current_stock is intentionally NOT writable here — it only
        # ever changes through PartUsage or StockAdjustment, both of
        # which go through the atomic F() update in models.py.
        # minimum_stock, unlike current_stock, IS writable — same
        # treatment as unit_price, since both are values a shop owner
        # sets and adjusts directly, not derived from stock movement.
        # The Sprint 7 taxonomy fields (item_type, vehicle_brand,
        # fluid_brand, viscosity_grade, reorder_cadence) are also
        # writable, same treatment.
        read_only_fields = ["id", "current_stock", "created_at", "updated_at"]

    def validate(self, data):
        """
        Sprint 7, Task 7.1 — enforces the SPARE_PART/FLUID mutual-
        exclusivity invariant. DRF's ModelSerializer does NOT call
        Model.full_clean()/clean() automatically, so this explicitly
        builds a transient, correctly-merged Part (existing instance
        fields overridden by whatever's actually changing in this
        request) and calls its real Part.clean() — the single source
        of truth for this rule, per Chris's own confirmed call, not a
        second copy of the same logic living here.
        """
        taxonomy_fields = ("item_type", "vehicle_brand", "fluid_brand", "viscosity_grade")
        merged = {
            field: data.get(field, getattr(self.instance, field, None) if self.instance else None)
            for field in taxonomy_fields
        }
        # item_type always has a real default even on a brand-new,
        # not-yet-saved instance — Part.ItemType.SPARE_PART matches
        # the model field's own default.
        if merged["item_type"] is None:
            merged["item_type"] = Part.ItemType.SPARE_PART
        for field in ("vehicle_brand", "fluid_brand", "viscosity_grade"):
            if merged[field] is None:
                merged[field] = ""

        temp = Part(**merged)
        try:
            temp.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict)
        return data


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


class StockOpnameLineItemSerializer(serializers.ModelSerializer):
    """
    Sprint 7, Task 7.3. `variance` is a real computed property
    (physical_count - system_stock_at_time), null until a count is
    actually recorded — never defaulted to 0, matching the model's
    own "genuinely uncounted, not zero" distinction.
    """
    part_name = serializers.CharField(source="part.name", read_only=True)
    unit      = serializers.CharField(source="part.unit", read_only=True)
    variance  = serializers.SerializerMethodField()

    class Meta:
        model  = StockOpnameLineItem
        fields = [
            "id", "part", "part_name", "unit",
            "system_stock_at_time", "physical_count", "variance",
        ]
        # physical_count is writable ONLY through
        # StockOpnameLineItem.record_count() — called from the
        # session's own PATCH view, never directly through this
        # serializer, so it's read-only here (the view mutates the
        # model instance, then re-serializes for the response).
        read_only_fields = ["id", "part_name", "unit", "system_stock_at_time", "physical_count", "variance"]

    def get_variance(self, obj):
        return obj.variance


class StockOpnameSessionSerializer(serializers.ModelSerializer):
    """
    Sprint 7, Task 7.3. Entirely read-only from this serializer's own
    point of view — sessions are only ever created via
    StockOpnameSession.start_session() and completed via .complete(),
    both real model methods with their own validation, never via a
    generic serializer.save().
    """
    line_items = StockOpnameLineItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = StockOpnameSession
        fields = [
            "id", "number", "status", "completed_at",
            "created_by", "created_by_name", "line_items", "created_at", "updated_at",
        ]
        read_only_fields = fields
