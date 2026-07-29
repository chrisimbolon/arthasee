# =============================================================================
# === backend/apps/contracts/serializers.py ===
# =============================================================================
from rest_framework import serializers

from .models import (Contract, ContractImport, ContractLineItem,
                     ContractVehicle, TerminPeriod)


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class TerminPeriodSerializer(serializers.ModelSerializer):
    is_realized = serializers.BooleanField(read_only=True)
    is_overdue  = serializers.BooleanField(read_only=True)

    class Meta:
        model  = TerminPeriod
        fields = [
            "id", "contract", "sequence", "jatuh_tempo",
            "amount_expected", "amount_received", "received_at",
            "is_realized", "is_overdue", "created_at",
        ]
        # Entirely system-managed — generated in full at Contract
        # creation, jatuh_tempo/amount_expected computed, never
        # hand-typed. The only write path is the dedicated realize/
        # endpoint (via record_realization()), same "this only
        # happens through its own explicit action" discipline as
        # WorkOrderStage.started_at/completed_at.
        read_only_fields = fields


class ContractLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ContractLineItem
        fields = [
            "id", "contract_vehicle", "source_row_no", "description",
            "volume", "unit", "unit_price", "subtotal", "status",
            "superseded_by", "created_at",
        ]
        # Never created/edited directly via a plain API call — the
        # only way a ContractLineItem is ever created or superseded is
        # through ContractImport.apply(), same "this only happens
        # through the promotion" discipline as PartUsage/InvoiceLineItem.
        read_only_fields = fields


class ContractVehicleSerializer(serializers.ModelSerializer):
    plate_number  = serializers.CharField(source="vehicle.plate_number", read_only=True)
    vehicle_model = serializers.CharField(source="vehicle.model", read_only=True)
    line_items    = serializers.SerializerMethodField()

    class Meta:
        model  = ContractVehicle
        fields = ["id", "contract", "vehicle", "plate_number", "vehicle_model", "allocated_budget", "line_items"]
        read_only_fields = ["id", "plate_number", "vehicle_model", "line_items"]

    def get_line_items(self, obj):
        # Only ever the current ACTIVE menu for this vehicle — this is
        # what a WorkOrder should be picking from, not the full,
        # superseded-included history.
        active = obj.line_items.filter(status="ACTIVE").order_by("source_row_no")
        return ContractLineItemSerializer(active, many=True).data


class ContractSerializer(serializers.ModelSerializer):
    customer_name    = serializers.CharField(source="customer.name", read_only=True)
    contract_vehicles = ContractVehicleSerializer(many=True, read_only=True)
    termin_periods   = TerminPeriodSerializer(many=True, read_only=True)
    created_by_name  = serializers.CharField(source="created_by.full_name", read_only=True, default=None)

    class Meta:
        model  = Contract
        fields = [
            "id", "customer", "customer_name", "title", "fiscal_year",
            "termin_count", "start_date", "status", "contract_vehicles", "termin_periods",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "customer_name", "contract_vehicles", "termin_periods",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def validate_customer(self, customer):
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return customer
        if customer.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Pelanggan tidak ditemukan.")
        return customer


class ContractListSerializer(ContractSerializer):
    """Lighter version for list views — no nested vehicles/line items/
    termin periods, same reasoning as every other *ListSerializer in
    this codebase."""
    class Meta(ContractSerializer.Meta):
        fields = [f for f in ContractSerializer.Meta.fields if f not in ("contract_vehicles", "termin_periods")]


class ContractImportSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", read_only=True, default=None)
    applied_by_name  = serializers.CharField(source="applied_by.full_name", read_only=True, default=None)
    totals_match     = serializers.BooleanField(read_only=True)

    class Meta:
        model  = ContractImport
        fields = [
            "id", "contract", "original_file", "status", "parsed_diff",
            "document_total", "computed_total", "totals_match", "parse_error",
            "uploaded_by", "uploaded_by_name", "uploaded_at",
            "applied_by", "applied_by_name", "applied_at",
        ]
        read_only_fields = [
            "id", "status", "parsed_diff", "document_total", "computed_total",
            "totals_match", "parse_error", "uploaded_by", "uploaded_by_name",
            "uploaded_at", "applied_by", "applied_by_name", "applied_at",
        ]
