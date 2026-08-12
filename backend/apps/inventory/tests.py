# =============================================================================
# === backend/apps/inventory/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderJobLine
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Part, PartUsage, StockAdjustment


class InventoryAPITestBase(APITestCase):
    """
    Deliberately its own base fixture, not imported from
    apps.service.tests — apps.inventory should be independently
    testable without a hard dependency on another app's test module,
    same loose-coupling instinct as serializers.py's local
    _user_org_ids copy. A little setUp duplication is a fair trade
    for that.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.inventory@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Budi Pelanggan")
        self.client.force_authenticate(user=self.owner)


class PartInventoryTests(InventoryAPITestBase):

    def setUp(self):
        super().setUp()
        self.part = Part.objects.create(
            organization=self.org, name="Busi", sku="BSI-001",
            unit="pcs", unit_price=Decimal("25000.00"),
        )
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 7001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.service_record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-20", odometer_km=10000,
            issue_description="Ganti busi",
        )

    def test_create_part_via_api_starts_at_zero_stock(self):
        resp = self.client.post(
            "/api/parts/",
            {"name": "Filter Oli", "unit": "pcs", "unit_price": 45000},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data["part"]["current_stock"]), Decimal("0.00"))

    def test_current_stock_is_read_only_via_api(self):
        resp = self.client.put(
            f"/api/parts/{self.part.id}/",
            {"current_stock": "9999.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("0.00"))

    def test_stock_adjustment_restock_increases_stock(self):
        resp = self.client.post(
            f"/api/parts/{self.part.id}/adjustments/",
            {"quantity_change": "20.00", "reason": "restock"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("20.00"))

    def test_stock_adjustment_damage_decreases_stock(self):
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("20.00"), reason="restock",
        )
        resp = self.client.post(
            f"/api/parts/{self.part.id}/adjustments/",
            {"quantity_change": "-3.00", "reason": "damage"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("17.00"))

    def test_part_usage_deducts_stock_matching_mades_own_example(self):
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("20.00"), reason="restock",
        )
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "4.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("16.00"))
        self.assertEqual(resp.data["warnings"], [])

    def test_part_usage_snapshots_price_not_a_live_reference(self):
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("20.00"), reason="restock",
        )
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "2.00"},
            format="json",
        )
        usage_id = resp.data["part_usage"]["id"]

        self.part.unit_price = Decimal("99999.00")
        self.part.save(update_fields=["unit_price"])

        usage = PartUsage.objects.get(id=usage_id)
        self.assertEqual(usage.unit_price_at_time, Decimal("25000.00"))

    def test_part_usage_allows_negative_stock_but_returns_a_warning(self):
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "5.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(len(resp.data["warnings"]) > 0)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("-5.00"))

    def test_low_stock_filter(self):
        """
        Updated for the real per-part minimum_stock field (previously
        relied on the old global "<=5" default, which no longer
        exists). Both parts now get an explicit threshold — this test
        proves the SAME real behavior it always proved (a part below
        its own threshold flags, a well-stocked one doesn't), just
        against the new, real per-part mechanism instead of an
        implicit global rule.
        """
        self.part.minimum_stock = Decimal("5.00")
        self.part.save(update_fields=["minimum_stock"])
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("3.00"), reason="restock",
        )
        well_stocked = Part.objects.create(
            organization=self.org, name="Oli Mesin", unit="liter", unit_price=Decimal("105000.00"),
            minimum_stock=Decimal("5.00"),
        )
        StockAdjustment.objects.create(
            organization=self.org, part=well_stocked, quantity_change=Decimal("50.00"), reason="restock",
        )
        resp = self.client.get("/api/parts/?low_stock=true")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Busi")


    def test_part_search_by_name_or_sku(self):
        by_sku = self.client.get("/api/parts/?search=BSI-001")
        self.assertEqual(by_sku.data["count"], 1)
        by_name = self.client.get("/api/parts/?search=Busi")
        self.assertEqual(by_name.data["count"], 1)


class InventoryProtectedDeletionTests(InventoryAPITestBase):
    """Part's own version of the Principle 2 protected-deletion tests
    — see apps.service.tests.Principle2ProtectedDeletionTests for the
    Customer/Vehicle equivalents."""

    def test_part_with_usage_history_cannot_be_deleted(self):
        part = Part.objects.create(
            organization=self.org, name="Busi Protected Test", unit="pcs", unit_price=Decimal("25000.00"),
        )
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 3334 CC", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        service_record = ServiceRecord.objects.create(
            organization=self.org, vehicle=vehicle,
            service_date="2026-07-19", odometer_km=10000,
            issue_description="Ganti busi",
        )
        PartUsage.objects.create(
            organization=self.org, service_record=service_record, part=part,
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("25000.00"),
        )
        resp = self.client.delete(f"/api/parts/{part.id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Part.objects.filter(id=part.id).exists())

    def test_part_without_usage_history_can_be_deleted(self):
        empty_part = Part.objects.create(
            organization=self.org, name="Never Used Part", unit="pcs", unit_price=Decimal("1000.00"),
        )
        resp = self.client.delete(f"/api/parts/{empty_part.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Part.objects.filter(id=empty_part.id).exists())


class InventoryTenantIsolationTests(InventoryAPITestBase):

    def setUp(self):
        super().setUp()
        self.part = Part.objects.create(
            organization=self.org, name="Busi", unit="pcs", unit_price=Decimal("25000.00"),
        )
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 8001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.service_record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-20", odometer_km=10000,
            issue_description="Ganti busi",
        )
        self.other_org = Organization.objects.create(name="Bengkel Lain Inventaris")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherinventory@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_see_org_a_parts(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get("/api/parts/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_retrieve_org_a_part_detail(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/parts/{self.part.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_create_stock_adjustment_against_cross_org_part(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.post(
            f"/api/parts/{self.part.id}/adjustments/",
            {"quantity_change": "10.00", "reason": "restock"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("0.00"))

    def test_cannot_create_part_usage_with_another_orgs_part(self):
        other_part = Part.objects.create(
            organization=self.other_org, name="Part Lain", unit="pcs", unit_price=Decimal("1000.00"),
        )
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(other_part.id), "quantity": "1.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_create_part_usage_against_cross_org_service_record(self):
        other_customer = Customer.objects.create(organization=self.other_org, name="Other Customer")
        other_vehicle = Vehicle.objects.create(
            organization=self.other_org, customer=other_customer,
            plate_number="BP 8002 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Other Car",
        )
        other_service_record = ServiceRecord.objects.create(
            organization=self.other_org, vehicle=other_vehicle,
            service_date="2026-07-20", odometer_km=1000,
            issue_description="x",
        )
        resp = self.client.post(
            f"/api/service-records/{other_service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "1.00"},
            format="json",
        )
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST))


class PartUsageFrozenAfterInvoiceTests(InventoryAPITestBase):
    """
    Proves the actual gap Sansan's review surfaced: PartUsageListView
    previously only checked tenant ownership, never whether an
    Invoice already existed — meaning a direct API call (no UI bug
    required) could still add usage to a ServiceRecord whose Invoice
    had already snapshotted a different set of line items, silently
    drifting stock and the invoice apart.
    """

    def setUp(self):
        super().setUp()
        self.part = Part.objects.create(
            organization=self.org, name="Busi", unit="pcs", unit_price=Decimal("25000.00"),
        )
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("20.00"), reason="restock",
        )
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 7002 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        # Invoice creation now hard-requires a mechanic (Made's own
        # 31 Jul rule) — self.service_record is created through a
        # real WorkOrder.close() call, with a mechanic assigned, so
        # the two tests below that create a real Invoice from it
        # satisfy that precondition without this class needing to
        # test mechanic assignment itself, which isn't its purpose.
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic,
        )
        # Made's own confirmed real-world rule, 2 Aug — Chris
        # witnessed it directly at Arya Motor: EVERY job goes through
        # QC before being marked done, even a routine oil change or
        # spark plug replacement. WorkOrder.close() now correctly
        # rejects closing directly from OPEN or IN_PROGRESS (see
        # apps.workorders.models.WorkOrder.close()) — a real
        # precondition, not test boilerplate to skip.
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
        self.service_record = work_order.close(closed_by=self.owner)

    def test_can_add_part_usage_before_invoice_exists(self):
        """Sanity check the guard doesn't over-block the normal case."""
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "2.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_cannot_add_part_usage_after_invoice_exists(self):
        Invoice.objects.create(service_record=self.service_record, created_by=self.owner)

        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "1.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_rejected_attempt_does_not_touch_stock(self):
        """
        Not just the status code — proves the actual side effect
        (stock deduction) genuinely never happened, matching this
        project's habit of verifying real state, not just HTTP codes.
        """
        Invoice.objects.create(service_record=self.service_record, created_by=self.owner)
        self.part.refresh_from_db()
        stock_before = self.part.current_stock

        self.client.post(
            f"/api/service-records/{self.service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "5.00"},
            format="json",
        )

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, stock_before)

class StockSummaryTests(APITestCase):
    """
    Pure logic tests against reports.py directly — no HTTP needed
    here, same TestCase/APITestCase split apps.analytics.tests
    already uses for the same reason (some tests are about the
    aggregation itself, some are about the endpoint wiring).
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor Summary", invoice_code="AMS")

    def test_summary_counts_and_total_value(self):
        from . import reports
        Part.objects.create(
            organization=self.org, name="A", current_stock=Decimal("10"),
            unit_price=Decimal("1000"), minimum_stock=Decimal("5"),
        )
        Part.objects.create(
            organization=self.org, name="B", current_stock=Decimal("2"),
            unit_price=Decimal("500"), minimum_stock=Decimal("5"),
        )  # below its own threshold -> low stock
        Part.objects.create(
            organization=self.org, name="C", current_stock=Decimal("0"),
            unit_price=Decimal("200"), minimum_stock=Decimal("0"),
        )  # completely out, no threshold ever configured -> out of stock

        result = reports.stock_summary(self.org)
        self.assertEqual(result["total_parts"], 3)
        self.assertEqual(result["total_stock_value"], Decimal("11000"))  # 10*1000 + 2*500 + 0*200
        self.assertEqual(result["low_stock_count"], 1)
        self.assertEqual(result["out_of_stock_count"], 1)

    def test_low_stock_and_out_of_stock_never_double_count(self):
        from . import reports
        Part.objects.create(
            organization=self.org, name="Zero With Threshold",
            current_stock=Decimal("0"), minimum_stock=Decimal("5"),
        )
        result = reports.stock_summary(self.org)
        self.assertEqual(result["out_of_stock_count"], 1)
        self.assertEqual(result["low_stock_count"], 0)


class LowStockFilterAPITests(InventoryAPITestBase):
    """
    Real proof the OLD global "<=5" rule is genuinely gone, replaced
    by the per-part threshold. Reuses InventoryAPITestBase's real
    org/owner/auth setup rather than duplicating it.
    """

    def test_high_stock_with_no_configured_threshold_never_flags(self):
        """
        The exact real behavior change this whole fix was for — a
        part with 50 units on hand and no configured threshold must
        NOT show as low stock just because it happens to be under
        some old generic global cutoff that no longer exists.
        """
        Part.objects.create(organization=self.org, name="Plenty", current_stock=Decimal("50"), minimum_stock=Decimal("0"))
        resp = self.client.get("/api/parts/?low_stock=true")
        self.assertEqual(resp.data["count"], 0)

    def test_part_below_its_own_configured_threshold_flags(self):
        Part.objects.create(organization=self.org, name="Configured Low", current_stock=Decimal("3"), minimum_stock=Decimal("10"))
        resp = self.client.get("/api/parts/?low_stock=true")
        self.assertEqual(resp.data["count"], 1)

    def test_completely_out_of_stock_flags_even_without_a_configured_threshold(self):
        Part.objects.create(organization=self.org, name="Zero No Threshold", current_stock=Decimal("0"), minimum_stock=Decimal("0"))
        resp = self.client.get("/api/parts/?low_stock=true")
        self.assertEqual(resp.data["count"], 1)

    def test_stock_summary_endpoint(self):
        Part.objects.create(organization=self.org, name="A", current_stock=Decimal("5"), unit_price=Decimal("1000"))
        resp = self.client.get("/api/parts/stock-summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total_parts"], 1)
        self.assertIn("total_stock_value_basis", resp.data)


class MovementHistoryTests(APITestCase):
    """Pure logic tests against reports.movement_history() directly."""

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor Movements", invoice_code="AMM")
        self.customer = Customer.objects.create(organization=self.org, name="Test Customer")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 9001 AA",
            manufacture_year=2020, vehicle_type="Mobil", model="Test Model",
        )
        self.service_record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle, service_date="2026-08-01",
            odometer_km=1000, issue_description="Test",
        )

    def test_merges_usage_and_adjustment_and_sorts_chronologically(self):
        from . import reports
        part = Part.objects.create(organization=self.org, name="P", current_stock=Decimal("15"), unit_price=Decimal("100"))
        StockAdjustment.objects.create(organization=self.org, part=part, quantity_change=Decimal("20"), reason="restock")
        PartUsage.objects.create(
            organization=self.org, service_record=self.service_record, part=part,
            quantity=Decimal("5"), unit_price_at_time=Decimal("100"),
        )

        rows = reports.movement_history(part)
        self.assertEqual(len(rows), 2)
        types = {r["type"] for r in rows}
        self.assertEqual(types, {"usage", "adjustment"})

        usage_row = next(r for r in rows if r["type"] == "usage")
        # Usage always shows as a real negative — consumption, never
        # a sign the caller has to reinterpret.
        self.assertEqual(usage_row["quantity_change"], Decimal("-5"))

        adjustment_row = next(r for r in rows if r["type"] == "adjustment")
        self.assertEqual(adjustment_row["quantity_change"], Decimal("20"))
        self.assertEqual(adjustment_row["reason"], "Restock / Pembelian")


class MovementHistoryAPITests(InventoryAPITestBase):
    """The one real HTTP smoke test for the new endpoint — separated
    from MovementHistoryTests so that class can stay a focused,
    pure-logic suite without an odd one-off HTTP call inside it."""

    def test_movement_history_endpoint(self):
        part = Part.objects.create(organization=self.org, name="P", current_stock=Decimal("10"), unit_price=Decimal("100"))
        StockAdjustment.objects.create(organization=self.org, part=part, quantity_change=Decimal("10"), reason="restock")

        resp = self.client.get(f"/api/parts/{part.id}/movements/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["movements"]), 1)