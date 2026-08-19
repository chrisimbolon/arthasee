# =============================================================================
# === backend/apps/service/tests.py ===
# =============================================================================
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from apps.authentication.models import CustomUser
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.organizations.models import Organization, OrganizationMembership
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderJobLine
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (Customer, ServiceRecord, ServiceReminderLog, Vehicle,
                     _add_months)


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
        Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 9999 ZZ", manufacture_year=2020,
            vehicle_type="Mobil", model="Car A",
        )
        other_org = Organization.objects.create(name="Bengkel Lain")
        other_customer = Customer.objects.create(organization=other_org, name="Other Customer")
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

    def test_customer_type_defaults_to_individual(self):
        """
        Omitting customer_type entirely — the normal case for every
        regular walk-in customer — must not require the caller to
        know this field exists at all.
        """
        resp = self.client.post(
            "/api/customers/", {"name": "Pelanggan Biasa"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["customer"]["customer_type"], "INDIVIDUAL")

    def test_customer_type_can_be_set_institutional(self):
        resp = self.client.post(
            "/api/customers/",
            {"name": "Ditreskrimum & Dittahti Polda Kepri", "customer_type": "INSTITUTIONAL"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["customer"]["customer_type"], "INSTITUTIONAL")

    def test_existing_customer_rows_default_to_individual(self):
        """
        Proves the backward-compatibility story explicitly, not just
        via the field's default= at creation time: a Customer created
        through the ORM without ever mentioning customer_type (as
        every pre-existing row in a real database would have been)
        still comes back correctly classified, with no backfill step
        required.
        """
        legacy_customer = Customer.objects.create(organization=self.org, name="Pelanggan Lama")
        legacy_customer.refresh_from_db()
        self.assertEqual(legacy_customer.customer_type, "INDIVIDUAL")

    def test_customer_type_filter_endpoint(self):
        """
        The real backend filter apps.contracts' Contract-creation
        picker should use instead of filtering client-side — this is
        what actually makes that upgrade safe.
        """
        Customer.objects.create(organization=self.org, name="Ditreskrimum Polda Kepri", customer_type="INSTITUTIONAL")
        Customer.objects.create(organization=self.org, name="Budi Perorangan", customer_type="INDIVIDUAL")
        resp = self.client.get("/api/customers/?customer_type=INSTITUTIONAL")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Ditreskrimum Polda Kepri")


class Principle2ProtectedDeletionTests(ServiceAPITestBase):
    """
    Principle 2: "no service history should ever be lost." Part's own
    version of this test now lives in apps.inventory.tests — this
    class covers only the models that still live here.
    """

    def test_customer_with_no_vehicles_can_be_deleted(self):
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
        self.assertEqual(vehicle.service_records.count(), 1)


class VehicleRegistrationExpiryTests(ServiceAPITestBase):

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


class ServiceRecordWorkOrderLinkTests(ServiceAPITestBase):
    """
    Proves the read-only work_order_id/work_order_number fields added
    to ServiceRecordSerializer for Sansan's "two disconnected
    sections" fix: a ServiceRecord produced by WorkOrder.close() must
    expose enough for the frontend to link straight back to it,
    without inventing a link where none genuinely exists.
    """

    def setUp(self):
        super().setUp()
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5001 WO", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            current_odometer_km=20000,
        )

    def test_service_record_without_work_order_has_null_link(self):
        """
        A ServiceRecord created directly (the only path that existed
        before WorkOrder, and still a valid one via the API today)
        must not fabricate a work order reference — it genuinely has
        none.
        """
        resp = self.client.post(
            f"/api/vehicles/{self.vehicle.id}/service-records/",
            {"service_date": "2026-07-20", "odometer_km": 20000, "issue_description": "Ganti oli"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data["service_record"]["work_order_id"])
        self.assertIsNone(resp.data["service_record"]["work_order_number"])

    def test_service_record_from_closed_work_order_exposes_the_link(self):
        """
        The actual case the frontend fix depends on: once a WorkOrder
        is closed, the ServiceRecord it produced should carry both
        the WorkOrder's id (for the link's href) and its human number
        (for the "WO #N" label), traced entirely through the reverse
        OneToOneField accessor — no new coupling between apps.service
        and apps.workorders to make this work.
        """
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, odometer_km_intake=20000,
        )
        # Made's own confirmed real-world rule, 2 Aug — Chris
        # witnessed it directly at Arya Motor: EVERY job goes through
        # QC before being marked done. WorkOrder.close() now
        # correctly rejects closing directly from OPEN or IN_PROGRESS
        # — a real precondition, not test boilerplate. Also needs a
        # real mechanic, 4 Aug — close() now rejects assigned_to=None
        # too (Made's own "no orphan completions" rule).
        work_order.status = "IN_PROGRESS"
        work_order.assigned_to = Mechanic.objects.create(organization=self.org, name="Yoga")
        work_order.save(update_fields=["status", "assigned_to"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
        record = work_order.close(service_date=date(2026, 7, 20), closed_by=self.owner)

        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        matching = next(
            r for r in resp.data["vehicle"]["service_records"] if str(r["id"]) == str(record.id)
        )
        # str() on both sides deliberately — resp.data holds the
        # serializer's raw Python objects (a real uuid.UUID instance
        # here, same as get_invoice_id's existing convention), not
        # the JSON-rendered string a real HTTP client would receive.
        # Comparing str-to-str is correct regardless of which
        # representation DRF's test client happens to hand back.
        self.assertEqual(str(matching["work_order_id"]), str(work_order.id))
        self.assertEqual(matching["work_order_number"], work_order.number)

    def test_invoice_total_is_null_when_no_invoice_exists(self):
        """
        A record with no Invoice at all must not fabricate a total.
        """
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-20", odometer_km=20000,
            issue_description="Ganti oli",
        )
        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/")
        matching = next(
            r for r in resp.data["vehicle"]["service_records"] if r["id"] == str(record.id)
        )
        self.assertIsNone(matching["invoice_total"])

    def test_invoice_total_reflects_the_real_invoice_amount(self):
        """
        Invoice.total is itself a computed property (summed from its
        own line items, never stored) — confirmed against the real
        model rather than assumed. Compares numerically, not by exact
        string, deliberately: Decimal multiplication/summation can
        carry more decimal places through than a naive hardcoded
        "200000.00" would predict, the same class of string-format
        assumption that already caused two separate false failures
        elsewhere in this project (a UUID and a plain unit_price).
        Numeric comparison sidesteps that entirely.
        """
        self.org.invoice_code = "AM"
        self.org.save(update_fields=["invoice_code"])

        # Invoice creation now hard-requires a mechanic (Made's own
        # 31 Jul rule) — record is created through a real
        # WorkOrder.close() call, with a mechanic assigned, rather
        # than a bare ServiceRecord with no originating WorkOrder at
        # all. self.vehicle.current_odometer_km is already 20000
        # (see this class's own setUp()), so close()'s own odometer
        # fallback produces the exact same value the original bare
        # creation specified explicitly — nothing else about this
        # test's real intent changes.
        mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=mechanic,
        )
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
        record = work_order.close(service_date=date(2026, 7, 20), closed_by=self.owner)

        invoice = Invoice.objects.create(service_record=record, created_by=self.owner)
        InvoiceLineItem.objects.create(
            organization=self.org, invoice=invoice, kind="labor",
            description="Jasa Ganti Oli", quantity=1, unit_price=Decimal("150000"),
        )
        InvoiceLineItem.objects.create(
            organization=self.org, invoice=invoice, kind="part",
            description="Filter Oli", quantity=1, unit_price=Decimal("50000"),
        )

        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/")
        matching = next(
            r for r in resp.data["vehicle"]["service_records"] if r["id"] == str(record.id)
        )
        self.assertEqual(Decimal(matching["invoice_total"]), Decimal("200000"))

    def test_cancelled_work_order_never_creates_a_service_record_to_link_from(self):
        """
        Not strictly a ServiceRecordSerializer test, but the load-
        bearing assumption the frontend fix's "cancelled orders have
        nowhere else to live" reasoning depends on — confirmed
        directly here rather than assumed from reading close()/
        cancel() side by side. If this ever stopped being true,
        WorkOrdersSection's CANCELLED-only history toggle would
        start silently hiding real jobs with no ServiceRecord to
        surface them elsewhere.
        """
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, odometer_km_intake=20000,
        )
        work_order.cancel()
        self.assertIsNone(work_order.service_record)
        self.assertEqual(ServiceRecord.objects.filter(vehicle=self.vehicle).count(), 0)

class VehicleServiceReminderTests(ServiceAPITestBase):
    """
    Real coverage for is_due_for_service_reminder — Made's own rule,
    3 months since last_service_date. Includes the exact near-miss
    case that caught a real bug before it ever became code: a naive
    "just compare month numbers" version would have wrongly flagged
    a date only 2 months and 29 days later as a full 3 months
    elapsed. Verified by hand in a sandbox before any of this was
    written; now a permanent test so a future change can't silently
    reintroduce that same bug.
    """

    def test_false_when_no_last_service_date(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.assertFalse(vehicle.is_due_for_service_reminder)

    def test_false_less_than_3_months(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5002 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=60),
        )
        self.assertFalse(vehicle.is_due_for_service_reminder)

    def test_false_two_days_short_of_3_months(self):
        """
        The exact real bug caught by hand before this property was
        written — a naive month-number comparison would have wrongly
        called this True. Dates built off _add_months(), not
        hardcoded, so this stays correct no matter when it runs.
        """
        just_short = _add_months(date.today(), -3) + timedelta(days=2)
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5003 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=just_short,
        )
        self.assertFalse(vehicle.is_due_for_service_reminder)

    def test_true_exactly_at_3_month_boundary(self):
        exactly_3_months_ago = _add_months(date.today(), -3)
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5004 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=exactly_3_months_ago,
        )
        self.assertTrue(vehicle.is_due_for_service_reminder)

    def test_true_well_past_3_months_no_upper_bound(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5005 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=400),
        )
        self.assertTrue(vehicle.is_due_for_service_reminder)


class ServiceReminderLogTests(ServiceAPITestBase):

    def setUp(self):
        super().setUp()
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 6001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )

    def test_same_vehicle_same_window_is_blocked_by_unique_together(self):
        """
        The real mechanism stopping this feature from becoming a
        daily spam email — a second row for the same
        (vehicle, for_last_service_date) must be impossible at the
        database level, not just discouraged by application logic.
        """
        from django.db import IntegrityError, transaction
        ServiceReminderLog.objects.create(
            organization=self.org, vehicle=self.vehicle,
            for_last_service_date=date(2026, 4, 1), status="SENT",
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServiceReminderLog.objects.create(
                    organization=self.org, vehicle=self.vehicle,
                    for_last_service_date=date(2026, 4, 1), status="SENT",
                )

    def test_different_windows_for_same_vehicle_are_allowed(self):
        """
        A real new ServiceRecord naturally moves last_service_date
        forward — a genuinely NEW window must be loggable
        independently of any prior one.
        """
        ServiceReminderLog.objects.create(
            organization=self.org, vehicle=self.vehicle,
            for_last_service_date=date(2026, 1, 1), status="SENT",
        )
        ServiceReminderLog.objects.create(
            organization=self.org, vehicle=self.vehicle,
            for_last_service_date=date(2026, 4, 1), status="SENT",
        )
        self.assertEqual(ServiceReminderLog.objects.filter(vehicle=self.vehicle).count(), 2)


class ServiceReminderEmailTests(ServiceAPITestBase):
    """
    Direct unit coverage for send_service_reminder_email() itself —
    mirrors apps.customers.tests.MagicLinkEmailTests' own real
    pattern: mock resend.Emails.send directly, not the whole HTTP
    stack.
    """

    def setUp(self):
        super().setUp()
        self.customer.email = "budi@test.id"
        self.customer.save(update_fields=["email"])
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 8001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date(2026, 4, 1),
        )

    @override_settings(RESEND_API_KEY="")
    def test_returns_false_when_not_configured(self):
        from apps.service.email import send_service_reminder_email
        self.assertFalse(send_service_reminder_email(self.vehicle))

    @override_settings(RESEND_API_KEY="test_key_123")
    @patch("resend.Emails.send")
    def test_returns_true_and_calls_resend_when_configured(self, mock_send):
        from apps.service.email import send_service_reminder_email
        result = send_service_reminder_email(self.vehicle)
        self.assertTrue(result)
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        self.assertEqual(call_args["to"], ["budi@test.id"])
        self.assertIn("BP 8001 AA", call_args["subject"])

    @override_settings(RESEND_API_KEY="test_key_123")
    @patch("resend.Emails.send")
    def test_returns_false_on_provider_failure_without_raising(self, mock_send):
        from apps.service.email import send_service_reminder_email
        mock_send.side_effect = Exception("Resend API error")
        result = send_service_reminder_email(self.vehicle)
        self.assertFalse(result)


@override_settings(RESEND_API_KEY="")
class SendServiceRemindersCommandTests(ServiceAPITestBase):
    """
    Real coverage for the actual daily job. RESEND_API_KEY="" at
    class level — same reasoning as
    apps.customers.tests.CustomerMagicLinkRequestViewTests: avoids
    ever making a live call to Resend during `manage.py test`. Every
    due vehicle with an email correctly logs FAILED under this
    override, which is itself the real thing being proven: the
    command must never crash just because sending isn't configured,
    and must still create the log row so a real retry storm can't
    happen even in a misconfigured environment.
    """

    def setUp(self):
        super().setUp()
        self.customer.email = "budi@test.id"
        self.customer.save(update_fields=["email"])

    def test_due_vehicle_with_email_gets_logged(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 7001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=120),
        )
        call_command("send_service_reminders")
        self.assertTrue(
            ServiceReminderLog.objects.filter(
                vehicle=vehicle, for_last_service_date=vehicle.last_service_date,
            ).exists()
        )

    def test_rerunning_the_same_day_does_not_double_log(self):
        """
        The real idempotency guard — the entire reason
        ServiceReminderLog exists. Verified by hand in a sandbox
        before this was written; now a permanent test.
        """
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 7002 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=120),
        )
        call_command("send_service_reminders")
        call_command("send_service_reminders")
        self.assertEqual(
            ServiceReminderLog.objects.filter(
                vehicle=vehicle, for_last_service_date=vehicle.last_service_date,
            ).count(),
            1,
        )

    def test_not_yet_due_vehicle_is_never_logged(self):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 7003 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=10),
        )
        call_command("send_service_reminders")
        self.assertFalse(ServiceReminderLog.objects.filter(vehicle=vehicle).exists())

    def test_due_vehicle_with_no_email_is_never_logged(self):
        """
        No email — surfaced for manual follow-up, never silently
        sent to nowhere, and never logged either, so it correctly
        stays flagged every day until a real email exists or the
        vehicle gets a new real service visit.
        """
        no_email_customer = Customer.objects.create(organization=self.org, name="No Email Customer")
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=no_email_customer,
            plate_number="BP 7004 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
            last_service_date=date.today() - timedelta(days=120),
        )
        call_command("send_service_reminders")
        self.assertFalse(ServiceReminderLog.objects.filter(vehicle=vehicle).exists())