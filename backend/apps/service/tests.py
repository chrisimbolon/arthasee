# =============================================================================
# === backend/apps/service/tests.py ===
# =============================================================================
from datetime import date, timedelta
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (Customer, Part, PartUsage, ServiceRecord, StockAdjustment,
                     Vehicle)


class ServiceAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor")
        self.owner = CustomUser.objects.create_user(
            email="owner.service@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(
            organization=self.org, name="Budi Pelanggan", phone="081200000000",
        )
        self.client.force_authenticate(user=self.owner)


class VehicleServiceRecordTests(ServiceAPITestBase):

    def test_creating_service_record_updates_vehicle_last_service_fields(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1234 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=45000,
        )
        resp = self.client.post(
            f"/api/vehicles/{vehicle.id}/service-records/",
            {
                "service_date": "2026-07-19", "odometer_km": 45000,
                "issue_description": "Ganti oli", "parts_replaced": "Filter oli",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.last_service_date, date(2026, 7, 19))
        self.assertEqual(vehicle.last_service_odometer_km, 45000)

    def test_due_for_service_false_just_under_threshold(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1235 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=49999, last_service_odometer_km=45000,
        )
        self.assertFalse(vehicle.is_due_for_service)

    def test_due_for_service_true_exactly_at_threshold(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1236 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=50000, last_service_odometer_km=45000,
        )
        self.assertTrue(vehicle.is_due_for_service)

    def test_due_for_service_false_when_never_serviced(self):
        """No last_service_odometer_km at all — nothing to compare
        against, so never flagged due, not a crash."""
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1237 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=10000,
        )
        self.assertFalse(vehicle.is_due_for_service)

    def test_due_for_service_filter_endpoint(self):
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1238 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Due Car",
            current_odometer_km=50000, last_service_odometer_km=45000,
        )
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1239 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Not Due Car",
            current_odometer_km=46000, last_service_odometer_km=45000,
        )
        resp = self.client.get("/api/vehicles/?due_for_service=true")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["model"], "Due Car")

    def test_plate_number_unique_per_org_not_global(self):
        """Two unrelated shops CAN have a vehicle with the same
        plate — only duplicate within the same shop is rejected."""
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 9999 ZZ", manufacture_year=2020,
            vehicle_type="Mobil", model="Car A",
        )
        other_org = Organization.objects.create(name="Bengkel Lain")
        other_customer = Customer.objects.create(organization=other_org, name="Other Customer")
        # Should succeed — different org, same plate.
        Vehicle.objects.create(
            organization=other_org, customer=other_customer,
            plate_number="BP 9999 ZZ", manufacture_year=2021,
            vehicle_type="Mobil", model="Car B",
        )
        self.assertEqual(Vehicle.objects.filter(plate_number="BP 9999 ZZ").count(), 2)


class ServiceTenantIsolationTests(ServiceAPITestBase):

    def setUp(self):
        super().setUp()
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5555 AB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.other_org = Organization.objects.create(name="Bengkel Lain Isolasi")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherservice@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )
        self.other_customer = Customer.objects.create(organization=self.other_org, name="Customer Lain")

    def test_org_b_cannot_see_org_a_vehicles(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get("/api/vehicles/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_retrieve_org_a_vehicle_detail(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_create_vehicle_with_cross_org_customer(self):
        """The specific guard validate_customer() exists for — a
        request naming another org's customer must be rejected, not
        silently create a Vehicle that resolves to the wrong org."""
        resp = self.client.post(
            "/api/vehicles/",
            {
                "customer": str(self.other_customer.id),
                "plate_number": "BP 6666 AB", "manufacture_year": 2020,
                "vehicle_type": "Mobil", "model": "Sneaky Car",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_create_service_record_for_cross_org_vehicle(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.post(
            f"/api/vehicles/{self.vehicle.id}/service-records/",
            {"service_date": "2026-07-19", "odometer_km": 1000, "issue_description": "x"},
            format="json",
        )
        # get_object() 404s before validate_vehicle() would even run,
        # since the nested URL itself is tenant-scoped via
        # get_queryset() filtering inside ServiceRecordListView.
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST))


class CustomerAPITests(ServiceAPITestBase):

    def test_create_customer(self):
        resp = self.client.post(
            "/api/customers/",
            {"name": "Andi Baru", "phone": "081211112222", "stnk_name": "PT Sewa Mobil"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["customer"]["stnk_name"], "PT Sewa Mobil")

    def test_customer_search_by_name(self):
        Customer.objects.create(organization=self.org, name="Siti Search")
        resp = self.client.get("/api/customers/?search=Siti")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)


class Principle2ProtectedDeletionTests(ServiceAPITestBase):
    """
    Principle 2: "no service history should ever be lost." PROTECT
    is the actual enforcement mechanism, not just a stated intention
    — these tests prove both halves: genuine mistakes stay fixable,
    real history becomes untouchable the moment it exists.
    """

    def test_customer_with_no_vehicles_can_be_deleted(self):
        """A genuine data-entry mistake — nothing lost, since there
        was never any real history attached."""
        empty_customer = Customer.objects.create(organization=self.org, name="Salah Ketik")
        resp = self.client.delete(f"/api/customers/{empty_customer.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Customer.objects.filter(id=empty_customer.id).exists())

    def test_customer_with_a_vehicle_cannot_be_deleted(self):
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1111 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        resp = self.client.delete(f"/api/customers/{self.customer.id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Customer.objects.filter(id=self.customer.id).exists())

    def test_vehicle_with_no_service_records_can_be_deleted(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 2222 BB", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        resp = self.client.delete(f"/api/vehicles/{vehicle.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(Vehicle.objects.filter(id=vehicle.id).exists())

    def test_vehicle_with_a_service_record_cannot_be_deleted(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 3333 CC", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=10000,
        )
        ServiceRecord.objects.create(
            organization=self.org, vehicle=vehicle,
            service_date="2026-07-19", odometer_km=10000,
            issue_description="Ganti oli",
        )
        resp = self.client.delete(f"/api/vehicles/{vehicle.id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(Vehicle.objects.filter(id=vehicle.id).exists())
        # And the service record itself is, of course, still there too.
        self.assertEqual(vehicle.service_records.count(), 1)

    def test_part_with_usage_history_cannot_be_deleted(self):
        """Same Principle 2 discipline extended to Sprint 1's new
        model — a Part that's actually been used must be exactly as
        protected as a Vehicle with a service record."""
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


# =============================================================================
# === Sprint 1: Vehicle registration expiry ===
# =============================================================================

class VehicleRegistrationExpiryTests(ServiceAPITestBase):
    """
    Covers is_registration_expiring_soon directly — including the
    already-expired case that the fix above exists specifically
    because of. Same boundary-testing discipline as
    VehicleServiceRecordTests' due-for-service tests (just under,
    exactly at, well past the threshold).
    """

    def test_expiring_soon_false_when_no_expiry_set(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.assertFalse(vehicle.is_registration_expiring_soon)

    def test_expiring_soon_false_when_far_in_future(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4002 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            registration_expiry=date.today() + timedelta(days=90),
        )
        self.assertFalse(vehicle.is_registration_expiring_soon)

    def test_expiring_soon_true_within_30_days(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4003 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            registration_expiry=date.today() + timedelta(days=15),
        )
        self.assertTrue(vehicle.is_registration_expiring_soon)

    def test_expiring_soon_true_exactly_at_30_day_boundary(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4004 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            registration_expiry=date.today() + timedelta(days=30),
        )
        self.assertTrue(vehicle.is_registration_expiring_soon)

    def test_expiring_soon_true_when_already_expired(self):
        """
        The exact case the fix above targets: expiry in the past must
        still read as True, not fall through to False the way the
        original `date.today() <= expiry <= ...` comparison did.
        """
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4005 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            registration_expiry=date.today() - timedelta(days=5),
        )
        self.assertTrue(vehicle.is_registration_expiring_soon)

    def test_registration_expiring_soon_filter_endpoint(self):
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4006 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Expiring Car",
            registration_expiry=date.today() + timedelta(days=10),
        )
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 4007 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Not Expiring Car",
            registration_expiry=date.today() + timedelta(days=200),
        )
        resp = self.client.get("/api/vehicles/?registration_expiring_soon=true")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["model"], "Expiring Car")


# =============================================================================
# === Sprint 1: Inventory ===
# =============================================================================

class PartInventoryTests(ServiceAPITestBase):

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
        """
        A direct PUT attempting to set current_stock must be
        silently ignored, not applied — it's read_only specifically
        so the only two ways stock moves are PartUsage and
        StockAdjustment, both leaving an audit trail. Without this
        test, a future refactor could accidentally make it writable
        again without anyone noticing until stock numbers stopped
        making sense.
        """
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
        """
        Directly the '20 − 4 = 16' example from Made's own
        handwritten notes — not an arbitrary number picked for the
        test.
        """
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
        """
        The actual bug this guards against: if unit_price_at_time
        were a live reference to Part.unit_price instead of a
        snapshot, changing the price next month would silently
        rewrite the cost of every past service that used this part.
        """
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
        """
        Deliberately a soft warning, not a hard 400 — see
        PartUsageSerializer.validate()'s own docstring for the
        real-world reasoning (a part used before the system caught
        up shouldn't block a mechanic from recording real work).
        """
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


class InventoryTenantIsolationTests(ServiceAPITestBase):
    """
    Same class of guards as ServiceTenantIsolationTests, extended to
    the three new Sprint 1 models. Part/PartUsage/StockAdjustment are
    just as capable of leaking across tenants as Vehicle/Customer if
    the validate_part() checks in serializers.py ever regress — these
    tests exist so a regression fails loudly here, not in production.
    """

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
        """
        StockAdjustmentListView.post() takes part_id straight from
        the URL rather than calling get_object() first — the only
        real guard is validate_part() inside the serializer. This
        test exists specifically to prove that guard actually fires,
        rather than assuming it does because the code "looks right."
        """
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
        # Own org's Part, but someone else's ServiceRecord — should
        # be rejected on the service_record side of the check, not
        # silently accepted because the Part itself was valid.
        resp = self.client.post(
            f"/api/service-records/{other_service_record.id}/part-usages/",
            {"part": str(self.part.id), "quantity": "1.00"},
            format="json",
        )
        self.assertIn(resp.status_code, (status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST))
