# =============================================================================
# === backend/apps/inventory/tests.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle

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
        self.org = Organization.objects.create(name="Arya Motor")
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
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("3.00"), reason="restock",
        )
        well_stocked = Part.objects.create(
            organization=self.org, name="Oli Mesin", unit="liter", unit_price=Decimal("105000.00"),
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
