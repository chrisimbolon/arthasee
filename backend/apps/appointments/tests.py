# =============================================================================
# === backend/apps/appointments/tests.py ===
# =============================================================================
from datetime import date, timedelta

from apps.organizations.models import Organization
from apps.service.models import Customer, Vehicle
from django.test import TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Appointment


class AppointmentsAPITestBase(APITestCase):
    """
    Same real fixture shape already proven throughout this project —
    one org, one Customer, one Vehicle. Capacity deliberately set to
    2, not the real default of 4 — makes "day is full" reachable in
    two bookings instead of four, keeping every test's own setup
    short without changing what's actually being proven.

    force_authenticate with the CUSTOMER instance directly, not a
    CustomUser — every appointments endpoint is protected by
    CustomerJWTAuthentication / IsCustomerAuthenticated, which
    expect request.user to BE the Customer, matching the same real
    pattern apps.customers' own Fase 2.5 customer-facing tests
    already use.
    """

    def setUp(self):
        self.org = Organization.objects.create(
            name="Arya Motor", invoice_code="AM", daily_appointment_capacity=2,
        )
        self.customer = Customer.objects.create(
            organization=self.org, name="Budi Pelanggan", email="budi@test.id",
        )
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1001 AA", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.client.force_authenticate(user=self.customer)

    def _make_other_customer_and_vehicle(self, suffix):
        customer = Customer.objects.create(organization=self.org, name=f"Customer {suffix}")
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=customer,
            plate_number=f"BP {suffix} XX", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        return customer, vehicle


class AppointmentModelTests(AppointmentsAPITestBase):
    """
    The real risk area — capacity counting and the two status
    transitions. Sequence verified by hand (fill capacity, cancel
    one, confirm the slot reopens; separately confirm CONVERTED
    still counts) before any of this was written.
    """

    def test_creates_successfully_under_capacity(self):
        appt = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle,
            requested_date=date.today() + timedelta(days=1),
        )
        self.assertIsNotNone(appt)
        self.assertEqual(appt.status, "CONFIRMED")

    def test_returns_none_when_capacity_reached(self):
        target_date = date.today() + timedelta(days=1)
        for i in range(2):  # capacity=2
            customer, vehicle = self._make_other_customer_and_vehicle(f"20{i}")
            self.assertIsNotNone(
                Appointment.create_if_available(customer=customer, vehicle=vehicle, requested_date=target_date)
            )
        third = Appointment.create_if_available(customer=self.customer, vehicle=self.vehicle, requested_date=target_date)
        self.assertIsNone(third)

    def test_cancelled_appointment_frees_the_slot(self):
        target_date = date.today() + timedelta(days=1)
        first = Appointment.create_if_available(customer=self.customer, vehicle=self.vehicle, requested_date=target_date)
        second_customer, second_vehicle = self._make_other_customer_and_vehicle("30")
        second = Appointment.create_if_available(customer=second_customer, vehicle=second_vehicle, requested_date=target_date)
        self.assertIsNotNone(second)  # capacity=2, both fit

        first.cancel()

        third_customer, third_vehicle = self._make_other_customer_and_vehicle("40")
        third = Appointment.create_if_available(customer=third_customer, vehicle=third_vehicle, requested_date=target_date)
        self.assertIsNotNone(third)  # first's cancellation freed the slot

    def test_converted_still_counts_against_capacity(self):
        """
        The exact case that would be easy to get wrong — CONVERTED
        must count the same as CONFIRMED, or a vehicle that's already
        physically arrived would silently free up a slot it's still
        occupying.
        """
        target_date = date.today() + timedelta(days=1)
        appt = Appointment.create_if_available(customer=self.customer, vehicle=self.vehicle, requested_date=target_date)
        appt.convert_to_work_order()

        second_customer, second_vehicle = self._make_other_customer_and_vehicle("50")
        second = Appointment.create_if_available(customer=second_customer, vehicle=second_vehicle, requested_date=target_date)
        self.assertIsNotNone(second)  # 1 converted + this new one = 2, still fits capacity=2

        third_customer, third_vehicle = self._make_other_customer_and_vehicle("60")
        third = Appointment.create_if_available(customer=third_customer, vehicle=third_vehicle, requested_date=target_date)
        self.assertIsNone(third)  # now genuinely full

    def test_cancel_raises_if_not_confirmed(self):
        appt = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle, requested_date=date.today() + timedelta(days=1),
        )
        appt.cancel()
        with self.assertRaises(ValueError):
            appt.cancel()

    def test_convert_to_work_order_creates_a_real_work_order(self):
        appt = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle, requested_date=date.today() + timedelta(days=1),
        )
        wo = appt.convert_to_work_order(received_by="Yoga")
        self.assertEqual(appt.status, "CONVERTED")
        self.assertEqual(appt.work_order, wo)
        self.assertEqual(wo.vehicle, self.vehicle)

    def test_convert_raises_if_not_confirmed(self):
        appt = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle, requested_date=date.today() + timedelta(days=1),
        )
        appt.cancel()
        with self.assertRaises(ValueError):
            appt.convert_to_work_order()


class AppointmentAvailabilityViewTests(AppointmentsAPITestBase):

    def test_returns_full_capacity_for_empty_days(self):
        resp = self.client.get("/api/customer/appointments/availability/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        days = resp.data["days"]
        self.assertEqual(len(days), 31)  # default 30-day forward window, inclusive
        for day in days:
            self.assertTrue(day["available"])
            self.assertEqual(day["capacity"], 2)
            self.assertEqual(day["booked"], 0)

    def test_reflects_a_real_booking(self):
        target_date = date.today() + timedelta(days=1)
        Appointment.create_if_available(customer=self.customer, vehicle=self.vehicle, requested_date=target_date)
        resp = self.client.get("/api/customer/appointments/availability/")
        target_row = next(d for d in resp.data["days"] if d["date"] == target_date.isoformat())
        self.assertEqual(target_row["booked"], 1)
        self.assertTrue(target_row["available"])  # capacity=2, only 1 booked


class AppointmentListCreateViewTests(AppointmentsAPITestBase):

    def test_creates_a_real_appointment(self):
        resp = self.client.post("/api/customer/appointments/", {
            "vehicle_id": str(self.vehicle.id),
            "requested_date": (date.today() + timedelta(days=1)).isoformat(),
            "notes": "Ganti oli & cek rem",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_rejects_someone_elses_vehicle(self):
        """
        Real ownership check — a logged-in customer must never be
        able to book using a vehicle_id they happen to guess or
        construct.
        """
        _, other_vehicle = self._make_other_customer_and_vehicle("99")
        resp = self.client.post("/api/customer/appointments/", {
            "vehicle_id": str(other_vehicle.id),
            "requested_date": (date.today() + timedelta(days=1)).isoformat(),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_rejects_a_past_date(self):
        resp = self.client.post("/api/customer/appointments/", {
            "vehicle_id": str(self.vehicle.id),
            "requested_date": (date.today() - timedelta(days=1)).isoformat(),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_returns_409_when_day_is_full(self):
        target_date = date.today() + timedelta(days=1)
        for i in range(2):  # capacity=2
            customer, vehicle = self._make_other_customer_and_vehicle(f"70{i}")
            Appointment.create_if_available(customer=customer, vehicle=vehicle, requested_date=target_date)

        resp = self.client.post("/api/customer/appointments/", {
            "vehicle_id": str(self.vehicle.id),
            "requested_date": target_date.isoformat(),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_list_only_returns_own_appointments(self):
        Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle, requested_date=date.today() + timedelta(days=1),
        )
        other_customer, other_vehicle = self._make_other_customer_and_vehicle("80")
        Appointment.create_if_available(
            customer=other_customer, vehicle=other_vehicle, requested_date=date.today() + timedelta(days=1),
        )

        resp = self.client.get("/api/customer/appointments/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)


class AppointmentCancelViewTests(AppointmentsAPITestBase):

    def test_cancels_own_appointment(self):
        appt = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle, requested_date=date.today() + timedelta(days=1),
        )
        resp = self.client.post(f"/api/customer/appointments/{appt.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "CANCELLED")

    def test_cannot_cancel_someone_elses_appointment(self):
        other_customer, other_vehicle = self._make_other_customer_and_vehicle("90")
        appt = Appointment.create_if_available(
            customer=other_customer, vehicle=other_vehicle, requested_date=date.today() + timedelta(days=1),
        )
        resp = self.client.post(f"/api/customer/appointments/{appt.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

class AppointmentConvertTransactionTests(TransactionTestCase):
    """
    Real regression test for a genuine bug caught live: calling
    convert_to_work_order() with no surrounding transaction crashed
    with TransactionManagementError, because WorkOrder.save() calls
    WorkOrderSequence.next_number(), which needs select_for_update()
    — and Django refuses to run that outside an active transaction.

    Deliberately TransactionTestCase, not the usual APITestCase used
    everywhere else in this file. Django's regular TestCase already
    wraps every test in its own outer transaction — select_for_update()
    would always have something to nest inside regardless of whether
    convert_to_work_order() opens its own transaction.atomic() or not.
    A test written with the normal TestCase would pass whether or not
    the real fix was even applied — false confidence, not real
    coverage. TransactionTestCase does NOT wrap tests in an outer
    transaction (it resets via TRUNCATE instead), so this is the one
    test in the whole suite that actually exercises the real, literal
    condition that broke in production.
    """

    def setUp(self):
        self.org = Organization.objects.create(
            name="Arya Motor Txn Test", invoice_code="AMTX", daily_appointment_capacity=4,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Budi", email="budi@test.id")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1234 TX", manufacture_year=2020,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.appointment = Appointment.create_if_available(
            customer=self.customer, vehicle=self.vehicle,
            requested_date=date.today() + timedelta(days=1),
        )

    def test_convert_succeeds_with_no_outer_transaction(self):
        """
        Called directly, with no surrounding transaction.atomic() from
        the caller — exactly the real condition that crashed in
        production, since the view itself never wraps this call.
        """
        work_order = self.appointment.convert_to_work_order(received_by="Staff")
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, "CONVERTED")
        self.assertEqual(self.appointment.work_order_id, work_order.id)