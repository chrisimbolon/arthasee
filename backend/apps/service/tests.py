# =============================================================================
# === backend/apps/service/tests.py ===
# =============================================================================
from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership

from .models import Customer, ServiceRecord, Vehicle


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
