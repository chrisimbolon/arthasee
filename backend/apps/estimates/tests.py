# =============================================================================
# === backend/apps/estimates/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.inventory.models import Part, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from apps.workorders.models import (WorkOrder, WorkOrderJobLine,
                                    WorkOrderMaterialLine)
from rest_framework import status
from rest_framework.test import APITestCase, APITransactionTestCase

from .models import Estimate, EstimateLineItem


class EstimateAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.estimates@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5501 AA", manufacture_year=2021,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.part = Part.objects.create(
            organization=self.org, name="Kampas Rem", unit="set", unit_price=Decimal("250000.00"),
        )
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("10.00"), reason="restock",
        )
        self.client.force_authenticate(user=self.owner)


class EstimateNumberingTests(EstimateAPITestBase):

    def test_number_is_plain_sequential(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["estimate"]["number"], "1")

    def test_sequence_increments(self):
        """
        Two DIFFERENT vehicles, deliberately — not the same vehicle
        twice. EstimateSequence is one row per organization, not per
        vehicle (same shape as WorkOrderSequence), so this is
        actually the more accurate way to prove numbering doesn't
        reset. It's also now a real requirement: the same-vehicle-
        twice version of this test would hit the new "one vehicle,
        one active job at a time" guard (see
        EstimateVehicleLockGuardTests below) and get a 409 instead of
        a second Estimate.
        """
        second_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5502 AA", manufacture_year=2021,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{second_vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(first.data["estimate"]["sequence_number"], 1)
        self.assertEqual(second.data["estimate"]["sequence_number"], 2)


class EstimateVehicleLockGuardTests(EstimateAPITestBase):
    """
    Chris's own explicit ask, 1 Aug QA: a real gap surfaced live on
    vehicle-detail — "Buat Estimasi" stayed enabled even while a
    WorkOrder for the same vehicle was already IN_PROGRESS, letting
    SA create a second, independent Estimate for a car already
    mid-repair (which would eventually promote into its own second
    WorkOrder via approve()). The rule: one vehicle, one active job
    (an active WorkOrder OR a PENDING Estimate) at a time.

    Mirror-image of WorkOrderVehicleLockGuardTests in
    apps.workorders.tests, which covers WorkOrderListView.post()'s
    own half of the exact same rule — kept as two separate classes,
    each testing its own real enforcement point, rather than one
    combined class straddling two apps.
    """

    def test_cannot_create_estimate_while_vehicle_has_an_open_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="OPEN")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(resp.data["success"])

    def test_cannot_create_estimate_while_vehicle_has_an_in_progress_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="IN_PROGRESS")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_create_estimate_while_vehicle_has_a_qc_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="QC")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_can_create_estimate_after_the_work_order_is_done(self):
        done_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        # Made's own confirmed real-world rule, 2 Aug — Chris
        # witnessed it directly at Arya Motor: EVERY job goes through
        # QC before being marked done, even a routine oil change or
        # spark plug replacement. WorkOrder.close() now correctly
        # rejects closing directly from OPEN or IN_PROGRESS (see
        # apps.workorders.models.WorkOrder.close()) — a real
        # precondition, not test boilerplate to skip.
        done_wo.status = "IN_PROGRESS"
        done_wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=done_wo, description="(qc placeholder)", is_done=True,
        )
        done_wo.status = "QC"
        done_wo.save(update_fields=["status"])
        done_wo.close(closed_by=self.owner)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_can_create_estimate_after_the_work_order_is_cancelled(self):
        cancelled_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        cancelled_wo.cancel()
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_cannot_create_estimate_while_vehicle_already_has_a_pending_estimate(self):
        """
        The milder, same-app version of the identical problem: two
        PENDING Estimates on one vehicle at once, each capable of
        independently promoting into its own WorkOrder via approve().
        """
        Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_approved_estimate_itself_does_not_block_once_its_work_order_is_closed(self):
        """
        Proves the guard's own-app check is scoped to status=
        "PENDING" specifically, not "any Estimate exists for this
        vehicle at all." Estimate.approve() promotes it straight
        into a real WorkOrder, which becomes the new, separate
        blocker (caught by the WorkOrder-status half of this same
        guard) in its own right — closing that WorkOrder removes the
        only real block left, and a fresh Estimate creation succeeds.
        """
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        work_order = estimate.approve(approved_by=self.owner)
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", is_done=True,
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
        work_order.close(closed_by=self.owner)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_can_create_estimate_when_previous_one_is_rejected(self):
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.reject(reason="NOT_NEEDED")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_guard_does_not_block_a_different_vehicle(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="IN_PROGRESS")
        other_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 5503 AA", manufacture_year=2021,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        resp = self.client.post(f"/api/vehicles/{other_vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_guard_scoped_to_organization(self):
        """
        Real defense-in-depth check, same reasoning as the mirrored
        test in WorkOrderVehicleLockGuardTests: an active WorkOrder
        on a same-numbered vehicle in a DIFFERENT organization must
        never block this one. The WorkOrder half of this guard
        queries WorkOrder.objects directly (not through
        self.get_queryset()), so this is worth proving explicitly
        rather than trusting it by inheritance alone.
        """
        other_org = Organization.objects.create(name="Bengkel Lain Est Lock", invoice_code="BLEL")
        other_customer = Customer.objects.create(organization=other_org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer, plate_number="BP 5501 AA",  # same plate on purpose
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        WorkOrder.objects.create(organization=other_org, vehicle=other_vehicle, status="IN_PROGRESS")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class EstimateLineItemTests(EstimateAPITestBase):

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_adding_part_line_does_not_touch_stock(self):
        """
        The core claim of the whole design: a proposed part line on
        an unapproved Estimate must have zero effect on real
        inventory. If this test fails, the speculative/committed
        boundary has been broken.
        """
        self.client.post(
            f"/api/estimates/{self.estimate.id}/line-items/",
            {"kind": "part", "description": "Kampas Rem", "quantity": "2.00",
             "unit_price": "250000.00", "part": str(self.part.id)},
            format="json",
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"), "stock must be untouched by a pending estimate")

    def test_create_labor_line(self):
        resp = self.client.post(
            f"/api/estimates/{self.estimate.id}/line-items/",
            {"kind": "labor", "description": "Ganti kampas rem", "unit_price": "150000.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["line_item"]["kind"], "labor")

    def test_cannot_add_line_after_estimate_decided(self):
        self.estimate.reject()
        resp = self.client.post(
            f"/api/estimates/{self.estimate.id}/line-items/",
            {"kind": "labor", "description": "x", "unit_price": "1000"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_total_reflects_all_lines(self):
        EstimateLineItem.objects.create(organization=self.org, estimate=self.estimate, kind="labor", description="Jasa", quantity=1, unit_price=Decimal("150000.00"))
        EstimateLineItem.objects.create(organization=self.org, estimate=self.estimate, kind="part", description="Kampas Rem", quantity=Decimal("2.00"), unit_price=Decimal("250000.00"), part=self.part)
        resp = self.client.get(f"/api/estimates/{self.estimate.id}/")
        self.assertEqual(Decimal(resp.data["estimate"]["total"]), Decimal("650000.00"))


class EstimateApprovalTests(EstimateAPITestBase):
    """
    The most important test class in this file — proves the actual
    promotion mechanism, not just that approve() 'works'.
    """

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle, diagnosis_notes="Rem bunyi")
        EstimateLineItem.objects.create(
            organization=self.org, estimate=self.estimate, kind="labor",
            description="Ganti kampas rem", quantity=1, unit_price=Decimal("150000.00"),
        )
        EstimateLineItem.objects.create(
            organization=self.org, estimate=self.estimate, kind="part",
            description="Kampas Rem", quantity=Decimal("2.00"), unit_price=Decimal("250000.00"), part=self.part,
        )

    def test_stock_untouched_before_approval_and_deducted_exactly_once_after(self):
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"), "stock must be untouched while still PENDING")

        self.estimate.approve(approved_by=self.owner)

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("8.00"), "approval must deduct exactly once, at this moment")

    def test_approve_creates_a_real_work_order_for_the_same_vehicle(self):
        work_order = self.estimate.approve(approved_by=self.owner)
        self.assertEqual(work_order.vehicle, self.vehicle)
        self.assertEqual(WorkOrder.objects.filter(vehicle=self.vehicle).count(), 1)

    def test_labor_line_becomes_a_job_line_with_price_folded_into_description(self):
        work_order = self.estimate.approve(approved_by=self.owner)
        job_line = WorkOrderJobLine.objects.get(work_order=work_order)
        self.assertIn("Ganti kampas rem", job_line.description)
        self.assertIn("150.000", job_line.description)

    def test_part_line_becomes_a_real_material_line(self):
        work_order = self.estimate.approve(approved_by=self.owner)
        material_line = WorkOrderMaterialLine.objects.get(work_order=work_order)
        self.assertEqual(material_line.part, self.part)
        self.assertEqual(material_line.quantity, Decimal("2.00"))

    def test_approve_sets_status_and_work_order_link(self):
        work_order = self.estimate.approve(approved_by=self.owner)
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, "APPROVED")
        self.assertEqual(self.estimate.work_order, work_order)

    def test_approve_carries_diagnosis_notes_into_work_order(self):
        work_order = self.estimate.approve(approved_by=self.owner)
        self.assertEqual(work_order.notes, "Rem bunyi")

    def test_work_order_can_look_back_at_its_originating_estimate(self):
        """Proves the reverse-accessor traceability works without any
        schema change to WorkOrder itself."""
        work_order = self.estimate.approve(approved_by=self.owner)
        self.assertEqual(work_order.estimate, self.estimate)

    def test_approve_via_api(self):
        resp = self.client.post(f"/api/estimates/{self.estimate.id}/approve/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["estimate"]["status"], "APPROVED")
        self.assertIsNotNone(resp.data["estimate"]["work_order"])

    def test_cannot_approve_twice(self):
        self.estimate.approve(approved_by=self.owner)
        with self.assertRaises(ValueError):
            self.estimate.approve(approved_by=self.owner)

    def test_cannot_approve_a_rejected_estimate(self):
        empty = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        empty.reject()
        with self.assertRaises(ValueError):
            empty.approve(approved_by=self.owner)


class EstimateRejectionTests(EstimateAPITestBase):

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_reject_records_reason_and_notes(self):
        self.estimate.reject(reason="TOO_EXPENSIVE", notes="Nego harga")
        self.estimate.refresh_from_db()
        self.assertEqual(self.estimate.status, "REJECTED")
        self.assertEqual(self.estimate.rejection_reason, "TOO_EXPENSIVE")

    def test_reject_creates_no_work_order(self):
        self.estimate.reject()
        self.assertFalse(WorkOrder.objects.filter(vehicle=self.vehicle).exists())

    def test_reject_via_api(self):
        resp = self.client.post(
            f"/api/estimates/{self.estimate.id}/reject/",
            {"reason": "WENT_ELSEWHERE", "notes": "Pilih bengkel lain"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["estimate"]["status"], "REJECTED")

    def test_cannot_reject_twice(self):
        self.estimate.reject()
        with self.assertRaises(ValueError):
            self.estimate.reject()


class EstimateTenantIsolationTests(EstimateAPITestBase):

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        self.other_org = Organization.objects.create(name="Bengkel Lain Estimasi", invoice_code="BL")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherestimate@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_see_org_a_estimates(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/estimates/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_add_line_with_cross_org_part(self):
        other_part = Part.objects.create(organization=self.other_org, name="Part Lain", unit="pcs", unit_price=Decimal("1000"))
        resp = self.client.post(
            f"/api/estimates/{self.estimate.id}/line-items/",
            {"kind": "part", "description": "x", "quantity": "1", "unit_price": "1000", "part": str(other_part.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class EstimateRealTransactionTests(APITransactionTestCase):
    """
    Deliberately APITransactionTestCase, not the usual APITestCase.
    APITestCase wraps every test in its own implicit transaction,
    which would mask a missing transaction.atomic() around Estimate
    creation exactly the way it once masked the identical bug in
    WorkOrderListView — every APITestCase-based test passed there
    too, right up until the first real HTTP request against a
    running server failed with 'select_for_update() cannot be used
    outside of a transaction.' This class exists specifically to
    catch that failure mode here if it's ever reintroduced.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.esttransaction@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 6002 AA", manufacture_year=2021,
            vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.client.force_authenticate(user=self.owner)

    def test_create_estimate_via_real_http_request(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["estimate"]["number"], "1")

    def test_approve_via_real_http_request(self):
        """approve() creates a WorkOrder, which itself claims a
        WorkOrderSequence number via select_for_update() — this
        proves that whole chain works without any implicit test-
        harness transaction to lean on. Both the estimate itself and
        the approval go through real HTTP requests, not direct model
        calls — a direct Estimate.objects.create() here would hit the
        identical unwrapped-transaction problem in the test's own
        code, defeating the point of this class."""
        create = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        estimate_id = create.data["estimate"]["id"]
        resp = self.client.post(f"/api/estimates/{estimate_id}/approve/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["estimate"]["status"], "APPROVED")


class EstimateOdometerTests(EstimateAPITestBase):
    """
    Chris's own framing, 31 Jul: "estimasi is like a gate" — real
    odometer capture belongs here, before any diagnosis/quote work.
    Hard block, not a soft warning, per Chris's explicit call.
    """

    def setUp(self):
        super().setUp()
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_last_service_odometer_km_reads_from_vehicle(self):
        """
        Not computed by this app at all — Vehicle.last_service_
        odometer_km is already a real, correctly-maintained field
        (kept in sync on every ServiceRecord.save()); this just
        proves the serializer actually surfaces it.
        """
        self.vehicle.last_service_odometer_km = 25000
        self.vehicle.save(update_fields=["last_service_odometer_km"])
        resp = self.client.get(f"/api/estimates/{self.estimate.id}/")
        self.assertEqual(resp.data["estimate"]["last_service_odometer_km"], 25000)

    def test_hard_blocks_when_below_last_service_odometer(self):
        self.vehicle.last_service_odometer_km = 25000
        self.vehicle.save(update_fields=["last_service_odometer_km"])
        resp = self.client.put(
            f"/api/estimates/{self.estimate.id}/", {"odometer_km_intake": 24000}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("odometer_km_intake", resp.data["errors"])

    def test_allows_when_exactly_equal_to_last_service_odometer(self):
        """Boundary case — exactly equal must be allowed, not just
        strictly greater. The validator uses '<', not '<=', on
        purpose: a car legitimately re-entering at the same reading
        it left at (e.g. a same-day comeback) is real, not invalid."""
        self.vehicle.last_service_odometer_km = 25000
        self.vehicle.save(update_fields=["last_service_odometer_km"])
        resp = self.client.put(
            f"/api/estimates/{self.estimate.id}/", {"odometer_km_intake": 25000}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_allows_when_above_last_service_odometer(self):
        self.vehicle.last_service_odometer_km = 25000
        self.vehicle.save(update_fields=["last_service_odometer_km"])
        resp = self.client.put(
            f"/api/estimates/{self.estimate.id}/", {"odometer_km_intake": 26500}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["estimate"]["odometer_km_intake"], 26500)

    def test_no_validation_error_when_vehicle_has_no_service_history(self):
        """
        self.vehicle's own last_service_odometer_km is None by
        default (never serviced) — nothing real to validate against,
        so any value must be accepted rather than blocked.
        """
        resp = self.client.put(
            f"/api/estimates/{self.estimate.id}/", {"odometer_km_intake": 100}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_cannot_update_odometer_after_estimate_decided(self):
        """The general 'already decided' 409 check runs before the
        allowed-fields filtering, so it applies to odometer_km_intake
        exactly the same way it already applies to diagnosis_notes —
        proving that's still true after extending the whitelist."""
        self.estimate.reject()
        resp = self.client.put(
            f"/api/estimates/{self.estimate.id}/", {"odometer_km_intake": 30000}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


class EstimateOdometerCarryForwardTests(EstimateAPITestBase):
    """Chris's explicit call, 31 Jul: carry forward automatically on
    approval, no re-entry."""

    def test_odometer_carries_forward_into_work_order_on_approve(self):
        estimate = Estimate.objects.create(
            organization=self.org, vehicle=self.vehicle, odometer_km_intake=27500,
        )
        work_order = estimate.approve(approved_by=self.owner)
        self.assertEqual(work_order.odometer_km_intake, 27500)

    def test_none_odometer_carries_forward_as_none(self):
        """An estimate that never had this filled in shouldn't
        silently invent a value on the resulting WorkOrder either."""
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        work_order = estimate.approve(approved_by=self.owner)
        self.assertIsNone(work_order.odometer_km_intake)
