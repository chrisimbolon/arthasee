# =============================================================================
# === backend/apps/service/serializers.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import serializers

from .models import Customer, ServiceRecord, Vehicle


def _user_org_ids(request):
    return request.user.memberships.filter(is_active=True).values_list(
        "organization_id", flat=True
    )


class CustomerSerializer(serializers.ModelSerializer):
    vehicle_count = serializers.IntegerField(source="vehicles.count", read_only=True)

    class Meta:
        model  = Customer
        fields = ["id", "name", "phone", "stnk_name", "customer_type", "vehicle_count", "created_at", "updated_at"]
        # customer_type deliberately editable, not read-only — unlike
        # vehicle_count (a derived count) or created_at, this is a
        # real classification the person creating the Customer should
        # set explicitly. Defaults to INDIVIDUAL server-side (see the
        # model), so omitting it entirely from a create payload still
        # behaves correctly — it's optional, not read-only.
        read_only_fields = ["id", "vehicle_count", "created_at", "updated_at"]


class ServiceRecordSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    part_usages      = serializers.SerializerMethodField()
    invoice_id        = serializers.SerializerMethodField()
    # Sansan's mockup for the Vehicle Timeline shows a real cost per
    # entry — the actual invoice total, not just whether one exists
    # (invoice_id) or what was originally quoted
    # (original_estimate_total). Same getattr-on-reverse-OneToOne
    # pattern as everything else on this serializer; Invoice.total
    # is itself already a computed property (summed from line items,
    # never stored), so this is read-only all the way down.
    invoice_total      = serializers.SerializerMethodField()
    original_estimate_total = serializers.SerializerMethodField()
    # 3 Sep 2026 — real UX gap found live: once a WorkOrder progresses
    # (or an Estimate's quotation needs re-checking against what was
    # actually charged), there was no way back to the original
    # Estimate document from the Riwayat Servis timeline — only its
    # TOTAL was ever surfaced (original_estimate_total above), never
    # its ID/number to actually link to. Same getattr-on-reverse-
    # OneToOne traversal that field already proves out
    # (ServiceRecord -> WorkOrder -> Estimate, entirely via reverse
    # accessors) — this is the exact same chain, just returning the
    # estimate's own identity instead of a computed sum. No schema
    # change: Estimate.work_order (a real OneToOneField, related_name
    # "estimate") already makes this reverse link free.
    estimate_id     = serializers.SerializerMethodField()
    estimate_number = serializers.SerializerMethodField()
    # Sansan's "two disconnected sections" review, resolved: rather
    # than merging WorkOrder/ServiceRecord into one data model (which
    # was explicitly ruled out — see PROJECT_STATE, "existing
    # ServiceRecord/Invoice history preserved exactly as-is, work
    # order is additive"), the fix is a read-only reverse link so the
    # frontend can render a completed WorkOrder as one linked entry
    # instead of two unrelated cards. Same getattr-on-reverse-
    # OneToOne pattern already proven by get_invoice_id and
    # get_original_estimate_total just below — no new coupling risk,
    # this app still imports nothing from apps.workorders.
    work_order_id     = serializers.SerializerMethodField()
    work_order_number = serializers.SerializerMethodField()

    class Meta:
        model  = ServiceRecord
        fields = [
            "id", "vehicle", "service_date", "odometer_km",
            "issue_description", "parts_replaced", "notes", "part_usages",
            "invoice_id", "invoice_total", "original_estimate_total",
            "estimate_id", "estimate_number",
            "work_order_id", "work_order_number",
            "created_by", "created_by_name", "created_at",
        ]
        read_only_fields = [
            "id", "created_by", "created_by_name", "created_at",
            "part_usages", "invoice_id", "invoice_total", "original_estimate_total",
            "estimate_id", "estimate_number",
            "work_order_id", "work_order_number",
        ]

    def get_part_usages(self, obj):
        return [
            {
                "id": pu.id, "part": pu.part_id, "part_name": pu.part.name,
                "quantity": pu.quantity, "unit": pu.part.unit,
                "unit_price_at_time": pu.unit_price_at_time,
            }
            for pu in obj.part_usages.select_related("part").all()
        ]

    def _get_estimate(self, obj):
        # Shared traversal — same reverse-accessor chain
        # get_original_estimate_total already established, factored
        # out so estimate_id/estimate_number don't each re-walk it
        # independently. getattr with a default is the correct way
        # to probe each reverse OneToOne: Django's
        # RelatedObjectDoesNotExist is deliberately a subclass of
        # AttributeError specifically so this works, for a record
        # that never went through a Work Order at all, or one that
        # did but was never quoted first (both entirely normal).
        work_order = getattr(obj, "work_order", None)
        if work_order is None:
            return None
        return getattr(work_order, "estimate", None)

    def get_original_estimate_total(self, obj):
        estimate = self._get_estimate(obj)
        if estimate is None:
            return None
        return sum((li.subtotal for li in estimate.line_items.all()), Decimal("0"))

    def get_estimate_id(self, obj):
        estimate = self._get_estimate(obj)
        return estimate.id if estimate else None

    def get_estimate_number(self, obj):
        # Split into its own field rather than overloading
        # estimate_id's presence — same reasoning as work_order_number
        # existing purely so the frontend gets the human-readable
        # number ("EST #33") for display without a second lookup.
        estimate = self._get_estimate(obj)
        return estimate.number if estimate else None

    def get_invoice_id(self, obj):
        # apps.invoicing.Invoice's OneToOneField reverse accessor —
        # getattr with a default is the correct, idiomatic way to
        # check a reverse OneToOne without a try/except: Django's
        # RelatedObjectDoesNotExist is deliberately a subclass of
        # both the target model's DoesNotExist AND AttributeError,
        # specifically so getattr(obj, 'invoice', None) works.
        invoice = getattr(obj, "invoice", None)
        return invoice.id if invoice else None

    def get_invoice_total(self, obj):
        invoice = getattr(obj, "invoice", None)
        return str(invoice.total) if invoice else None

    def get_work_order_id(self, obj):
        # Deliberately null for records created before WorkOrder
        # existed, or any future path that creates a ServiceRecord
        # without going through one — this field only ever surfaces
        # a genuine link, never fabricates one. A CANCELLED WorkOrder
        # never reaches this at all: WorkOrder.cancel() never sets
        # service_record, only close() does, so cancelled orders
        # correctly have no ServiceRecord to be found from.
        work_order = getattr(obj, "work_order", None)
        return work_order.id if work_order else None

    def get_work_order_number(self, obj):
        # Split into its own field rather than overloading
        # work_order_id's presence — the frontend wants the human
        # number ("WO #12") for display without a second lookup, same
        # reasoning as invoice_id existing purely to drive a UI
        # branch cheaply.
        work_order = getattr(obj, "work_order", None)
        return work_order.number if work_order else None

    def validate_vehicle(self, vehicle):
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
        request = self.context.get("request")
        if request is None or request.user.role == "super_admin":
            return customer
        if customer.organization_id not in _user_org_ids(request):
            raise serializers.ValidationError("Pelanggan tidak ditemukan.")
        return customer


class VehicleListSerializer(VehicleSerializer):
    class Meta(VehicleSerializer.Meta):
        fields = [f for f in VehicleSerializer.Meta.fields if f != "service_records"]
