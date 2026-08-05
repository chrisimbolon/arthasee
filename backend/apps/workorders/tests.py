# =============================================================================
# === backend/apps/workorders/tests.py ===
# =============================================================================
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import PropertyMock, patch

from apps.authentication.models import CustomUser
from apps.estimates.models import Estimate
from apps.inventory.models import Part, PartUsage, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APITransactionTestCase

from .models import (Mechanic, WorkOrder, WorkOrderJobLine,
                     WorkOrderMaterialLine, WorkOrderStage)


class WorkOrderAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.workorders@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1451 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Mitsubishi Xtrada",
            current_odometer_km=50000,
        )
        self.part = Part.objects.create(
            organization=self.org, name="Kampas Rem", unit="set", unit_price=Decimal("250000.00"),
        )
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("10.00"), reason="restock",
        )
        self.client.force_authenticate(user=self.owner)

    def _started(self, wo):
        """
        Chris's own catch, 2 Aug — caught live in production:
        WorkOrder.close() now correctly rejects closing directly from
        OPEN (see models.py) — a job must have actually been marked
        "Mulai Dikerjakan" before it can be marked done. Every
        existing test in this file that closes a WorkOrder purely as
        setup (its real focus is stock deduction, ServiceRecord
        creation, dashboard counts, etc. — not the OPEN->DONE rule
        itself) needs this first. Bypasses the real status endpoint
        deliberately — these tests aren't testing that transition,
        just need a real, valid precondition satisfied quickly.
        """
        wo.status = "IN_PROGRESS"
        wo.save(update_fields=["status"])
        return wo

    def _ready_to_close(self, wo):
        """
        Made's own confirmed real-world rule, 2 Aug — Chris witnessed
        it directly at Arya Motor: EVERY job goes through QC before
        being marked done, even a routine oil change or spark plug
        replacement, with Made himself personally doing QC on simple
        jobs. WorkOrder.close() now correctly rejects closing directly
        from IN_PROGRESS (see models.py) — every existing test that
        closes a WorkOrder purely as setup needs this, not just
        _started(). Creates one placeholder, already-done job line so
        the separate "Ajukan Pemeriksaan requires all work checked
        off" gate doesn't block this purely-setup transition — these
        tests aren't testing that gate either, just need a real,
        valid path to a closeable state.

        Also assigns a real mechanic, 4 Aug — Made's own explicit
        rule that same meeting: "Harus dicegat penerbitan WO selesai
        tanpa mekanik!" (no orphan completions). close() now rejects
        assigned_to=None too. Only assigns one if the caller hasn't
        already set one deliberately — a test specifically covering
        the no-mechanic rejection itself creates its own WorkOrder
        with assigned_to left unset and calls close() directly,
        bypassing this helper entirely (see
        WorkOrderNoMechanicHardBlockTests).
        """
        self._started(wo)
        if wo.assigned_to is None:
            mechanic = Mechanic.objects.create(organization=wo.organization, name="Yoga (test setup)")
            wo.assigned_to = mechanic
            wo.save(update_fields=["assigned_to"])
        WorkOrderJobLine.objects.create(
            organization=wo.organization, work_order=wo, description="(qc placeholder)", completed_at=timezone.now(),
        )
        wo.status = "QC"
        wo.save(update_fields=["status"])
        return wo


class WorkOrderNumberingTests(WorkOrderAPITestBase):

    def test_number_is_plain_sequential_no_prefix(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["work_order"]["number"], "1")
        self.assertEqual(resp.data["work_order"]["sequence_number"], 1)

    def test_sequence_increments_and_does_not_reset(self):
        """
        Two DIFFERENT vehicles, deliberately — not the same vehicle
        twice. WorkOrderSequence is one row per organization, not per
        vehicle (see WorkOrderSequence's own docstring), so this is
        actually the more accurate way to prove numbering doesn't
        reset. It's also now a real requirement, not just a style
        choice: the same-vehicle-twice version of this test would
        hit the new "one vehicle, one active job at a time" guard
        (see WorkOrderVehicleLockGuardTests below) and get a 409
        instead of a second WorkOrder.
        """
        second_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1451 AB", manufacture_year=2022,
            vehicle_type="Mobil", model="Mitsubishi Xtrada",
        )
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{second_vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(first.data["work_order"]["sequence_number"], 1)
        self.assertEqual(second.data["work_order"]["sequence_number"], 2)


class WorkOrderVehicleLockGuardTests(WorkOrderAPITestBase):
    """
    Chris's own explicit ask, 1 Aug QA: a real gap surfaced live on
    vehicle-detail — both "Buat Estimasi" and "Buat Work Order"
    stayed enabled even while a WorkOrder for that same vehicle was
    already IN_PROGRESS, letting SA create a second, independent job
    for a car already mid-repair. The rule: one vehicle, one active
    job (an active WorkOrder OR a PENDING Estimate) at a time.

    This class only covers WorkOrderListView.post()'s own half of the
    guard — the mirror-image check inside EstimateListView.post()
    (blocking a new Estimate while a WorkOrder or another PENDING
    Estimate is already active) belongs in apps.estimates.tests
    instead, matching how every other cross-app rule in this project
    is already tested at each of its own real enforcement points
    rather than once for both.
    """

    def test_cannot_create_work_order_while_vehicle_has_an_open_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="OPEN")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(resp.data["success"])

    def test_cannot_create_work_order_while_vehicle_has_an_in_progress_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="IN_PROGRESS")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_create_work_order_while_vehicle_has_a_qc_work_order(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="QC")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_can_create_work_order_after_the_previous_one_is_done(self):
        done_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self._ready_to_close(done_wo)
        done_wo.close(closed_by=self.owner)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_can_create_work_order_after_the_previous_one_is_cancelled(self):
        cancelled_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        cancelled_wo.cancel()
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_cannot_create_work_order_while_vehicle_has_a_pending_estimate(self):
        """
        The milder version of the same problem: a PENDING Estimate
        would eventually create its own WorkOrder via approve() — so
        this is checked here too, not just an existing active
        WorkOrder.
        """
        Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_approved_estimate_itself_does_not_block_once_its_work_order_is_closed(self):
        """
        Proves the guard's Estimate check is scoped to status=
        "PENDING" specifically, not "any Estimate exists for this
        vehicle at all." Estimate.approve() promotes it straight
        into a real WorkOrder (see Estimate.approve() in models.py),
        which becomes the new, separate blocker in its own right —
        closing that WorkOrder removes the only real block left, and
        a fresh creation succeeds. If the guard were wrongly checking
        "any Estimate" instead of "PENDING Estimate," this would
        still 409 even after the WorkOrder it produced is done.
        """
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        work_order = estimate.approve(approved_by=self.owner)
        self._ready_to_close(work_order)
        work_order.close(closed_by=self.owner)
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_can_create_work_order_when_estimate_is_rejected(self):
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.reject(reason="NOT_NEEDED")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_guard_does_not_block_a_different_vehicle(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, status="IN_PROGRESS")
        other_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 2000 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Test Car",
        )
        resp = self.client.post(f"/api/vehicles/{other_vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_guard_scoped_to_organization_not_just_vehicle_status(self):
        """
        Real defense-in-depth check: an active WorkOrder on the same-
        numbered vehicle in a DIFFERENT organization must never block
        this one — TenantScopedAPIView's own scoping already
        guarantees this everywhere else, but the guard's own query
        filters directly on WorkOrder.objects (not self.get_queryset()
        in EstimateListView's half of this check), so it's worth
        proving explicitly rather than trusting it by inheritance.
        """
        other_org = Organization.objects.create(name="Bengkel Lain WO Lock", invoice_code="BLWL")
        other_customer = Customer.objects.create(organization=other_org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer, plate_number="BP 1451 AA",  # same plate on purpose
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        WorkOrder.objects.create(organization=other_org, vehicle=other_vehicle, status="IN_PROGRESS")
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class WorkOrderJobLineTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_toggle_cycles_through_the_real_three_states(self):
        """
        Made's own confirmed handwritten note, 4 Aug: "Pekerjaan
        bertahap: jam mulai – jam selesai" — a single toggle used to
        flip straight to done; now it's a real 3-state cycle
        (Menunggu -> Sedang Berjalan -> Selesai -> back to Menunggu),
        each transition backed by a real timestamp.
        """
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "Bak belakang las reparasi"}, format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertFalse(create.data["job_line"]["is_done"])
        self.assertIsNone(create.data["job_line"]["started_at"])

        line_id = create.data["job_line"]["id"]
        # Chris's own catch, 2 Aug — caught live in production: a job
        # line couldn't be marked done before this until the WorkOrder
        # actually left OPEN — same real-work-must-have-begun rule as
        # WorkOrder.close() itself. A real precondition now, not test
        # boilerplate to skip.
        self._started(self.wo)

        # 1st toggle: Menunggu -> Sedang Berjalan
        first = self.client.patch(f"/api/work-orders/job-lines/{line_id}/toggle/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertFalse(first.data["job_line"]["is_done"])
        self.assertIsNotNone(first.data["job_line"]["started_at"])
        self.assertIsNone(first.data["job_line"]["completed_at"])

        # 2nd toggle: Sedang Berjalan -> Selesai
        second = self.client.patch(f"/api/work-orders/job-lines/{line_id}/toggle/")
        self.assertTrue(second.data["job_line"]["is_done"])
        self.assertIsNotNone(second.data["job_line"]["completed_at"])
        # started_at from the first toggle must survive untouched —
        # first-time-wins, same discipline as WorkOrderStage.
        self.assertEqual(first.data["job_line"]["started_at"], second.data["job_line"]["started_at"])

        # 3rd toggle: Selesai -> back to Menunggu (the real mistake-
        # correction path — WorkOrderJobLine.reset() on the backend)
        third = self.client.patch(f"/api/work-orders/job-lines/{line_id}/toggle/")
        self.assertFalse(third.data["job_line"]["is_done"])
        self.assertIsNone(third.data["job_line"]["started_at"])
        self.assertIsNone(third.data["job_line"]["completed_at"])

    def test_cannot_toggle_job_line_while_work_order_still_open(self):
        """
        The actual regression test for the bug this fixes — caught
        live from a real screenshot (WO #22, a job line struck
        through while status was still Terbuka/OPEN, "Mulai WO
        Sekarang" never clicked).
        """
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "Bongkar kaburator"}, format="json",
        )
        line_id = create.data["job_line"]["id"]
        toggle = self.client.patch(f"/api/work-orders/job-lines/{line_id}/toggle/")
        self.assertEqual(toggle.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(WorkOrderJobLine.objects.get(id=line_id).is_done)

    def test_cannot_add_job_line_to_cancelled_work_order(self):
        self.wo.status = "CANCELLED"
        self.wo.save(update_fields=["status"])
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "x"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


class WorkOrderJobLineEditDeleteTests(WorkOrderAPITestBase):
    """
    Chris's own explicit ask, 2 Aug — caught live from a real
    screenshot: a job line typed with a typo ("Pemasangan Kembal")
    had no way to ever be fixed, and no way to remove a wrongly-added
    item either. Only create() and toggle() existed before this.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.line = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, description="Ganti kampas rem",
        )

    def test_can_edit_description_of_an_open_job_line(self):
        resp = self.client.put(
            f"/api/work-orders/job-lines/{self.line.id}/",
            {"description": "Ganti kampas rem depan"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["job_line"]["description"], "Ganti kampas rem depan")
        self.line.refresh_from_db()
        self.assertEqual(self.line.description, "Ganti kampas rem depan")

    def test_editing_with_an_empty_description_is_rejected(self):
        resp = self.client.put(
            f"/api/work-orders/job-lines/{self.line.id}/",
            {"description": "   "}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.line.refresh_from_db()
        self.assertEqual(self.line.description, "Ganti kampas rem")

    def test_can_delete_an_open_job_line(self):
        resp = self.client.delete(f"/api/work-orders/job-lines/{self.line.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(WorkOrderJobLine.objects.filter(id=self.line.id).exists())

    def test_cannot_edit_job_line_once_work_order_is_done(self):
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        resp = self.client.put(
            f"/api/work-orders/job-lines/{self.line.id}/",
            {"description": "x"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_delete_job_line_once_work_order_is_cancelled(self):
        self.wo.cancel()
        resp = self.client.delete(f"/api/work-orders/job-lines/{self.line.id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(WorkOrderJobLine.objects.filter(id=self.line.id).exists())

    def test_cannot_edit_job_line_whose_own_stage_is_completed_even_if_work_order_still_open(self):
        """
        The real reason is_locked has two conditions, not one: a
        finished stage's own checklist shouldn't stay editable just
        because a sibling stage on the same, still-open WorkOrder is
        genuinely in progress.
        """
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Bongkar Gardan", sequence=1,
        )
        staged_line = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=stage, description="Kuras Cairan",
        )
        stage.complete()
        stage.save()

        resp = self.client.put(
            f"/api/work-orders/job-lines/{staged_line.id}/",
            {"description": "Kuras Cairan (revisi)"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        # The unstaged line from setUp, on the same still-OPEN-overall
        # WorkOrder, must remain genuinely editable — proves this is a
        # per-line lock, not an accidental whole-WorkOrder lock.
        other_resp = self.client.put(
            f"/api/work-orders/job-lines/{self.line.id}/",
            {"description": "Ganti kampas rem depan"}, format="json",
        )
        self.assertEqual(other_resp.status_code, status.HTTP_200_OK)

    def test_is_locked_is_false_by_default_on_a_fresh_open_line(self):
        self.assertFalse(self.line.is_locked)

    def test_is_locked_reflects_correctly_via_the_api(self):
        list_resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-lines/")
        self.assertFalse(list_resp.data["results"][0]["is_locked"])

        self.wo.cancel()
        list_resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-lines/")
        self.assertTrue(list_resp.data["results"][0]["is_locked"])


class WorkOrderMaterialLineTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_material_line_deducts_stock_in_real_time(self):
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "2.00"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("8.00"))

    def test_material_line_snapshots_price(self):
        self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "1.00"}, format="json",
        )
        self.part.unit_price = Decimal("999999.00")
        self.part.save(update_fields=["unit_price"])
        line = WorkOrderMaterialLine.objects.get(work_order=self.wo)
        self.assertEqual(line.unit_price_at_time, Decimal("250000.00"))

    def test_deleting_material_line_reverses_stock(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "3.00"}, format="json",
        )
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("7.00"))

        line_id = create.data["material_line"]["id"]
        delete = self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(delete.status_code, status.HTTP_200_OK)
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"))
        self.assertFalse(WorkOrderMaterialLine.objects.filter(id=line_id).exists())

    def test_cannot_delete_material_line_after_work_order_done(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "1.00"}, format="json",
        )
        line_id = create.data["material_line"]["id"]
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        delete = self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(delete.status_code, status.HTTP_409_CONFLICT)


class WorkOrderCloseTests(WorkOrderAPITestBase):
    """
    The most important test class in this file — proves the actual
    double-deduction-avoidance mechanism the whole design hinges on,
    not just that closing 'works'.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, odometer_km_intake=50500,
        )
        WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Ganti kampas rem")
        # Created directly (not via API) but still goes through the
        # model's own save() — real-time deduction fires exactly the
        # same way it would through the endpoint.
        WorkOrderMaterialLine.objects.create(
            organization=self.org, work_order=self.wo, part=self.part, quantity=Decimal("2.00"),
        )
        # Every test in this class closes self.wo — a real
        # precondition now that WorkOrder.close() correctly rejects
        # both OPEN and IN_PROGRESS (see models.py) — every job must
        # genuinely pass through QC, Made's own confirmed rule.
        # test_cannot_close_a_cancelled_work_order uses its own
        # separate empty_wo, unaffected by this.
        self._ready_to_close(self.wo)

    def test_close_backfills_a_stage_that_was_never_started_or_completed(self):
        """
        The actual regression test for the bug caught via a real
        customer-facing tracking link: WO #23 showed "Selesai"
        overall while its own "Overhaul" stage still sat at
        "Menunggu" — never explicitly started/completed via "Mulai
        Tahap"/"Selesaikan Tahap", even though the real work under it
        was done.
        """
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        self.assertIsNone(stage.started_at)
        self.assertIsNone(stage.completed_at)

        self.wo.close(closed_by=self.owner)

        stage.refresh_from_db()
        self.assertIsNotNone(stage.started_at)
        self.assertIsNotNone(stage.completed_at)

    def test_close_never_overwrites_a_stages_real_earlier_timestamps(self):
        """
        A stage genuinely completed for real, hours before the
        WorkOrder itself closes, must keep its own real, earlier
        timestamps — the backfill is only for stages that were never
        actually closed out, not a blanket "reset every timestamp to
        now" on every close().
        """
        real_started = timezone.now() - timedelta(hours=3)
        real_completed = timezone.now() - timedelta(hours=1)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
            started_at=real_started, completed_at=real_completed,
        )

        self.wo.close(closed_by=self.owner)

        stage.refresh_from_db()
        self.assertEqual(stage.started_at, real_started)
        self.assertEqual(stage.completed_at, real_completed)

    def test_close_only_backfills_completed_at_for_a_stage_already_genuinely_started(self):
        """
        Partial case: a stage genuinely started for real but never
        explicitly completed — close() must preserve the real
        started_at and only backfill the missing completed_at, not
        silently move the start time forward too.
        """
        real_started = timezone.now() - timedelta(hours=2)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
            started_at=real_started,
        )

        self.wo.close(closed_by=self.owner)

        stage.refresh_from_db()
        self.assertEqual(stage.started_at, real_started)
        self.assertIsNotNone(stage.completed_at)
        self.assertGreater(stage.completed_at, real_started)

    def test_stock_is_deducted_exactly_once_across_open_and_close(self):
        """
        The core claim: stock started at 10, one material line used 2
        while the WorkOrder was open (leaving 8) — closing the
        WorkOrder must NOT deduct a second time. If it did, stock
        would incorrectly read 6 instead of 8.
        """
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("8.00"), "stock should already reflect the material line")

        self.wo.close(closed_by=self.owner)

        self.part.refresh_from_db()
        self.assertEqual(
            self.part.current_stock, Decimal("8.00"),
            "closing must not deduct stock a second time for the same material line",
        )

    def test_close_creates_service_record_with_correct_fields(self):
        record = self.wo.close(closed_by=self.owner)
        self.assertEqual(record.vehicle, self.vehicle)
        self.assertEqual(record.odometer_km, 50500)
        self.assertIn("Ganti kampas rem", record.issue_description)
        self.assertIn("Kampas Rem", record.parts_replaced)

    def test_close_creates_matching_part_usage_with_same_price_snapshot(self):
        self.wo.close(closed_by=self.owner)
        usage = PartUsage.objects.get(service_record__work_order=self.wo)
        self.assertEqual(usage.quantity, Decimal("2.00"))
        self.assertEqual(usage.unit_price_at_time, Decimal("250000.00"))

    def test_close_links_work_order_to_the_new_service_record(self):
        record = self.wo.close(closed_by=self.owner)
        self.wo.refresh_from_db()
        self.assertEqual(self.wo.status, "DONE")
        self.assertEqual(self.wo.service_record, record)

    def test_close_via_api(self):
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/close/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["work_order"]["status"], "DONE")
        self.assertIsNotNone(resp.data["work_order"]["service_record"])

    def test_cannot_close_an_already_done_work_order(self):
        self.wo.close(closed_by=self.owner)
        with self.assertRaises(ValueError):
            self.wo.close(closed_by=self.owner)

    def test_cannot_close_a_cancelled_work_order(self):
        empty_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        empty_wo.cancel()
        with self.assertRaises(ValueError):
            empty_wo.close(closed_by=self.owner)

    def test_cannot_close_a_work_order_with_no_mechanic_assigned(self):
        """
        The actual regression test for Made's own explicit rule, 4
        Aug meeting: "Harus dicegat penerbitan WO selesai tanpa
        mekanik!" (no orphan completions). Caught live: a real
        WorkOrder had already reached "Selesai" with no assigned
        mechanic, and the existing block (item 22, 31 Jul) only ever
        fired later, downstream, at the "Buat Invoice" step — this is
        the real fix, catching it at the source. A fresh WorkOrder
        here, deliberately not self.wo (which setUp already gives a
        real mechanic to via _ready_to_close's own new behavior).
        """
        no_mechanic_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        no_mechanic_wo.status = "IN_PROGRESS"
        no_mechanic_wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=no_mechanic_wo, description="Ganti oli", completed_at=timezone.now(),
        )
        no_mechanic_wo.status = "QC"
        no_mechanic_wo.save(update_fields=["status"])
        self.assertIsNone(no_mechanic_wo.assigned_to)

        with self.assertRaises(ValueError):
            no_mechanic_wo.close(closed_by=self.owner)
        no_mechanic_wo.refresh_from_db()
        self.assertIsNone(no_mechanic_wo.service_record)
        self.assertEqual(no_mechanic_wo.status, "QC")

    def test_can_close_once_a_mechanic_is_assigned(self):
        no_mechanic_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        no_mechanic_wo.status = "IN_PROGRESS"
        no_mechanic_wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=no_mechanic_wo, description="Ganti oli", completed_at=timezone.now(),
        )
        no_mechanic_wo.status = "QC"
        no_mechanic_wo.assigned_to = Mechanic.objects.create(organization=self.org, name="Yoga")
        no_mechanic_wo.save(update_fields=["status", "assigned_to"])

        record = no_mechanic_wo.close(closed_by=self.owner)
        self.assertIsNotNone(record)
        no_mechanic_wo.refresh_from_db()
        self.assertEqual(no_mechanic_wo.status, "DONE")

    def test_no_mechanic_hard_block_via_api(self):
        """
        The real, end-to-end proof — not just that the model method
        raises, but that the actual /close/ endpoint a real click hits
        surfaces it correctly as a 409, same as every other close()
        precondition already proven this way.
        """
        no_mechanic_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        no_mechanic_wo.status = "IN_PROGRESS"
        no_mechanic_wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=no_mechanic_wo, description="Ganti oli", completed_at=timezone.now(),
        )
        no_mechanic_wo.status = "QC"
        no_mechanic_wo.save(update_fields=["status"])

        resp = self.client.post(f"/api/work-orders/{no_mechanic_wo.id}/close/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("mekanik", resp.data["message"].lower())

    def test_service_record_created_by_close_can_still_be_invoiced_normally(self):
        """
        The whole point of freezing into a real ServiceRecord — proves
        the Sprint 2 invoicing flow works completely unmodified
        against a WorkOrder-originated record.
        """
        from apps.invoicing.models import Invoice

        # Invoice creation now hard-requires a mechanic (Made's own
        # 31 Jul rule) — assigned here purely to satisfy that
        # precondition, not because this test is actually about
        # mechanic assignment.
        mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        self.wo.assigned_to = mechanic
        self.wo.save(update_fields=["assigned_to"])
        record = self.wo.close(closed_by=self.owner)
        invoice = Invoice.objects.create(service_record=record, created_by=self.owner)
        self.assertEqual(invoice.line_items.count(), 0)  # created directly, no line items added here
        self.assertTrue(invoice.number.startswith("INV/REG/AM/"))


class BackfillStageTimestampsCommandTests(WorkOrderAPITestBase):
    """
    Chris's own catch, 3 Aug: the WorkOrder.close() fix only prevents
    NEW stage-timestamp gaps going forward — it can't reach back and
    fix a WorkOrder that was already DONE before that fix shipped
    (confirmed live: WO #23 kept showing "Menunggu" on the public
    tracking page after the code fix was deployed). This command is
    the other half — a one-time backfill pass over existing data.
    """

    def setUp(self):
        # WorkOrderAPITestBase itself never creates a WorkOrder — only
        # WorkOrderCloseTests' own setUp does that, and this class
        # doesn't inherit from it. Caught by a real 6-test failure
        # (AttributeError: no attribute 'wo') the first time this ran.
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def _run_command(self):
        out = StringIO()
        call_command("backfill_stage_timestamps", stdout=out)
        return out.getvalue()

    def test_backfills_a_stage_left_open_on_an_already_done_work_order(self):
        self._ready_to_close(self.wo)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        self.wo.close(closed_by=self.owner)
        # Simulating the real bug: a WorkOrder closed BEFORE the
        # close()-side fix existed. Directly resetting the stage back
        # to null here, bypassing close()'s own new backfill logic,
        # so this test genuinely proves the command's own independent
        # fix — not accidentally re-testing close() itself.
        stage.started_at = None
        stage.completed_at = None
        stage.save(update_fields=["started_at", "completed_at"])

        self._run_command()

        stage.refresh_from_db()
        self.assertIsNotNone(stage.started_at)
        self.assertIsNotNone(stage.completed_at)

    def test_backfilled_timestamp_matches_the_work_orders_own_updated_at(self):
        self._ready_to_close(self.wo)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        self.wo.close(closed_by=self.owner)
        stage.started_at = None
        stage.completed_at = None
        stage.save(update_fields=["started_at", "completed_at"])
        self.wo.refresh_from_db()

        self._run_command()

        stage.refresh_from_db()
        self.assertEqual(stage.started_at, self.wo.updated_at)
        self.assertEqual(stage.completed_at, self.wo.updated_at)

    def test_never_overwrites_a_stages_real_existing_timestamps(self):
        self._ready_to_close(self.wo)
        real_started = timezone.now() - timedelta(hours=3)
        real_completed = timezone.now() - timedelta(hours=1)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
            started_at=real_started, completed_at=real_completed,
        )
        self.wo.close(closed_by=self.owner)

        self._run_command()

        stage.refresh_from_db()
        self.assertEqual(stage.started_at, real_started)
        self.assertEqual(stage.completed_at, real_completed)

    def test_does_not_touch_a_work_order_that_is_not_done(self):
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        # self.wo is still OPEN — not DONE — at this point.
        self._run_command()

        stage.refresh_from_db()
        self.assertIsNone(stage.started_at)
        self.assertIsNone(stage.completed_at)

    def test_is_safe_to_run_more_than_once(self):
        self._ready_to_close(self.wo)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        self.wo.close(closed_by=self.owner)
        stage.started_at = None
        stage.completed_at = None
        stage.save(update_fields=["started_at", "completed_at"])

        self._run_command()
        stage.refresh_from_db()
        first_started, first_completed = stage.started_at, stage.completed_at

        self._run_command()
        stage.refresh_from_db()
        self.assertEqual(stage.started_at, first_started)
        self.assertEqual(stage.completed_at, first_completed)

    def test_reports_a_real_summary(self):
        self._ready_to_close(self.wo)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Overhaul", sequence=1,
        )
        self.wo.close(closed_by=self.owner)
        stage.started_at = None
        stage.completed_at = None
        stage.save(update_fields=["started_at", "completed_at"])

        output = self._run_command()
        self.assertIn("1", output)  # 1 stage, 1 work order


class WorkOrderCancelTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderMaterialLine.objects.create(
            organization=self.org, work_order=self.wo, part=self.part, quantity=Decimal("4.00"),
        )

    def test_cancel_reverses_deducted_stock(self):
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("6.00"))

        self.wo.cancel()

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"))

    def test_cancel_creates_a_labeled_stock_adjustment(self):
        self.wo.cancel()
        adjustment = StockAdjustment.objects.filter(reason="work_order_cancelled", part=self.part).first()
        self.assertIsNotNone(adjustment)
        self.assertEqual(adjustment.quantity_change, Decimal("4.00"))
        self.assertIn(self.wo.number, adjustment.notes)

    def test_cannot_cancel_an_already_done_work_order(self):
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        with self.assertRaises(ValueError):
            self.wo.cancel()

    def test_cannot_cancel_an_already_cancelled_work_order(self):
        self.wo.cancel()
        with self.assertRaises(ValueError):
            self.wo.cancel()

    def test_cancel_via_api(self):
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["work_order"]["status"], "CANCELLED")


class WorkOrderStatusTransitionTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_can_move_through_open_pipeline_statuses(self):
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "IN_PROGRESS"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["work_order"]["status"], "IN_PROGRESS")

    def test_status_endpoint_rejects_done_and_cancelled(self):
        """DONE/CANCELLED must go through /close/ or /cancel/, which
        carry real side effects a bare status write must never
        trigger implicitly."""
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "DONE"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_move_to_qc_with_no_job_lines_at_all(self):
        """
        Chris's own explicit ask, 2 Aug — caught live in production:
        "Ajukan Pemeriksaan" sat right next to "Selesaikan Work Order"
        with no ordering signal, and nothing stopped submitting for
        QC before any real work was ever recorded. A WorkOrder with
        zero job lines has nothing to have verified.
        """
        self._started(self.wo)
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "QC"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_move_to_qc_while_a_job_line_is_still_unchecked(self):
        self._started(self.wo)
        WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Bongkar Gear Box")
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "QC"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_can_move_to_qc_once_every_job_line_is_done(self):
        self._started(self.wo)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Bongkar Gear Box")
        line.complete()
        line.save(update_fields=["started_at", "completed_at"])
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "QC"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["work_order"]["status"], "QC")

    def test_cannot_move_to_qc_when_only_some_job_lines_are_done(self):
        self._started(self.wo)
        done_line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Bongkar Gear Box")
        done_line.complete()
        done_line.save(update_fields=["started_at", "completed_at"])
        WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Pasang Gear Box Baru")
        resp = self.client.patch(f"/api/work-orders/{self.wo.id}/status/", {"status": "QC"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


class WorkOrderTenantIsolationTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.other_org = Organization.objects.create(name="Bengkel Lain WO", invoice_code="BL")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherwo@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_see_org_a_work_orders(self):
        """
        List endpoints under TenantScopedAPIView return an empty,
        correctly-scoped list rather than a 404 — same pattern as
        every other list view in this codebase (e.g.
        ServiceTenantIsolationTests.test_org_b_cannot_see_org_a_vehicles).
        The vehicle_id itself belongs to org A, but org B's queryset
        is filtered to org B's own organization_id first, so it can
        never see org A's WorkOrder rows regardless of which
        vehicle_id is requested.
        """
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/vehicles/{self.vehicle.id}/work-orders/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_add_material_line_with_cross_org_part(self):
        other_part = Part.objects.create(organization=self.other_org, name="Part Lain", unit="pcs", unit_price=Decimal("1000"))
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(other_part.id), "quantity": "1.00"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class WorkOrderRealTransactionTests(APITransactionTestCase):
    """
    Deliberately APITransactionTestCase, not the usual APITestCase
    used everywhere else in this file. APITestCase wraps every test
    method in its own implicit transaction (a performance shortcut,
    fast rollback instead of table truncation between tests) — which
    accidentally gives select_for_update() a transaction to attach to
    even when the actual view code never opened one itself. That
    masking is exactly what let WorkOrderListView.post() ship without
    its own transaction.atomic() wrapper: every APITestCase-based test
    passed, and the very first real HTTP request against a running
    server failed with 'select_for_update() cannot be used outside of
    a transaction.'

    APITransactionTestCase runs without that implicit wrapper — it's
    slower (real commits + truncation instead of rollback), which is
    exactly why it isn't used for every test in this file, only this
    one class, specifically to catch this exact failure mode again if
    it's ever reintroduced.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.wotransaction@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 9001 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Test Car",
        )
        # Second vehicle, needed by test_second_work_order_gets_next_
        # sequence_via_real_http_requests below — same reasoning as
        # WorkOrderNumberingTests.test_sequence_increments_and_does_
        # not_reset: proving org-scoped sequencing now genuinely
        # requires two different vehicles, since a second WorkOrder
        # on the SAME vehicle would correctly hit the new "one
        # vehicle, one active job" guard instead.
        self.second_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 9002 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Test Car",
        )
        self.client.force_authenticate(user=self.owner)

    def test_create_work_order_via_real_http_request_without_implicit_transaction(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["work_order"]["number"], "1")

    def test_second_work_order_gets_next_sequence_via_real_http_requests(self):
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{self.second_vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(first.data["work_order"]["sequence_number"], 1)
        self.assertEqual(second.data["work_order"]["sequence_number"], 2)


class WorkOrderMaterialLineDeletionReasonTests(WorkOrderAPITestBase):
    """
    Confirmed directly with Made: a customer cancelling an already-
    installed part mid-repair (a multi-day job, car stays overnight)
    is a real, recurring, distinct scenario from a mechanic simply
    correcting a data-entry mistake. Both still reverse stock the
    same way — this only proves the audit trail records the right
    reason for each.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_default_deletion_reason_is_correction(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "1.00"}, format="json",
        )
        line_id = create.data["material_line"]["id"]
        self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        adjustment = StockAdjustment.objects.filter(part=self.part, reason="correction").first()
        self.assertIsNotNone(adjustment)

    def test_can_record_customer_cancelled_reason_explicitly(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "1.00"}, format="json",
        )
        line_id = create.data["material_line"]["id"]
        self.client.delete(f"/api/work-orders/material-lines/{line_id}/", {"reason": "customer_cancelled_part"}, format="json")
        adjustment = StockAdjustment.objects.filter(part=self.part, reason="customer_cancelled_part").first()
        self.assertIsNotNone(adjustment)

    def test_invalid_reason_falls_back_to_correction(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/material-lines/",
            {"part": str(self.part.id), "quantity": "1.00"}, format="json",
        )
        line_id = create.data["material_line"]["id"]
        self.client.delete(f"/api/work-orders/material-lines/{line_id}/", {"reason": "made_up_value"}, format="json")
        adjustment = StockAdjustment.objects.filter(part=self.part).first()
        self.assertEqual(adjustment.reason, "correction")


class WorkOrderStartedAtTests(WorkOrderAPITestBase):
    """
    Made's own request — "jam mulai dikerjakan," the exact clock time
    work actually began. Confirmed with Chris: captured automatically
    the instant status first moves to IN_PROGRESS, and only ever
    meaningful for a Work Order that traces back to an approved
    Estimate.

    NOTE on test coverage: the "does have an Estimate origin" cases
    below use unittest.mock.patch.object to temporarily replace the
    WorkOrder.estimate class-level descriptor with a PropertyMock,
    rather than creating a real apps.estimates.models.Estimate row.
    This is deliberate, not a shortcut of convenience: "estimate" is
    a reverse OneToOneField descriptor, and Django's own __set__
    actually validates the assigned value's type — a plain
    `wo.estimate = object()` raises ValueError outright rather than
    silently working, which is exactly what happened the first time
    this test was written without checking. patch.object replaces
    the descriptor itself for the duration of the context manager,
    bypassing that validation entirely, which correctly isolates
    mark_started()'s own logic (it only ever calls
    getattr(self, "estimate", None)) from the real cross-app relation.
    A fuller integration test, creating a real Estimate and promoting
    it via approve(), would belong in apps.estimates.tests instead,
    matching how that promotion is already tested at its own source.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_work_started_at_is_null_until_in_progress(self):
        self.assertIsNone(self.wo.work_started_at)

    def test_moving_to_in_progress_without_estimate_origin_leaves_it_null(self):
        """
        The real, default case for most Work Orders — direct entry,
        no Estimate ever involved. Confirmed with Chris this field
        should never populate for this path, by design, not by
        omission.
        """
        resp = self.client.patch(
            f"/api/work-orders/{self.wo.id}/status/", {"status": "IN_PROGRESS"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["work_order"]["work_started_at"])

    def test_mark_started_sets_timestamp_when_estimate_origin_present(self):
        with patch.object(WorkOrder, "estimate", new_callable=PropertyMock) as mock_estimate:
            mock_estimate.return_value = object()  # any truthy stand-in
            self.wo.mark_started()
        self.assertIsNotNone(self.wo.work_started_at)

    def test_mark_started_is_a_noop_without_estimate_origin(self):
        self.wo.mark_started()
        self.assertIsNone(self.wo.work_started_at)

    def test_mark_started_never_overwrites_an_existing_timestamp(self):
        """
        First-time-wins: a Work Order that somehow cycles IN_PROGRESS
        -> QC -> IN_PROGRESS again (both legal OPEN_STATUSES
        transitions per WorkOrderStatusUpdateView) must not have its
        original start time silently replaced by the second entry.
        """
        with patch.object(WorkOrder, "estimate", new_callable=PropertyMock) as mock_estimate:
            mock_estimate.return_value = object()
            self.wo.mark_started()
            original = self.wo.work_started_at
            self.assertIsNotNone(original)

            self.wo.mark_started()
            self.assertEqual(self.wo.work_started_at, original)


class WorkOrderJobTicketPdfTests(WorkOrderAPITestBase):
    """
    Chris's own confirmed answers, 1 Aug: an internal, no-price job
    ticket for the mechanic, available the moment "Mulai Dikerjakan"
    is clicked.

    The gate is deliberately status != "OPEN", NOT work_started_at —
    caught mid-build, and directly follows from what
    WorkOrderStartedAtTests.test_moving_to_in_progress_without_
    estimate_origin_leaves_it_null already proves: work_started_at is
    Estimate-only and stays null forever for a direct-entry WorkOrder
    (the majority of real jobs). Gating on that field would have left
    the endpoint permanently 409 for most work orders — this class
    exists specifically to catch that regression if it's ever
    reintroduced, the same reasoning EstimateRealTransactionTests
    exists for its own once-real bug.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_returns_409_while_still_open(self):
        resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_available_once_in_progress_even_without_estimate_origin(self):
        """
        The actual regression test for the bug this class exists to
        prevent: a plain, direct-entry WorkOrder (no Estimate, the
        real default case) moved to IN_PROGRESS via the real status
        endpoint. work_started_at stays null (confirmed separately by
        WorkOrderStartedAtTests) — this must still succeed anyway.
        """
        patch_resp = self.client.patch(
            f"/api/work-orders/{self.wo.id}/status/", {"status": "IN_PROGRESS"}, format="json",
        )
        self.assertIsNone(patch_resp.data["work_order"]["work_started_at"])

        resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_available_during_qc(self):
        self.wo.status = "QC"
        self.wo.save(update_fields=["status"])
        resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_available_after_done(self):
        """A finished job's ticket should still be retrievable — e.g.
        Made wanting to reprint a record after the fact."""
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_known_edge_case_cancelled_straight_from_open_is_still_printable(self):
        """
        Documents a real, deliberately-accepted edge case rather than
        silently patching around it: a WorkOrder cancelled directly
        from OPEN (e.g. customer changed their mind before any work
        began) ends up with status="CANCELLED" — which is not "OPEN"
        — so this endpoint allows it through. There's no separate
        field distinguishing "was genuinely IN_PROGRESS at some
        point, then cancelled" from "went straight OPEN -> CANCELLED"
        for a direct-entry WorkOrder (work_started_at is null in both
        cases either way, per the same Estimate-only restriction).
        Accepted rather than engineered around: printing an
        essentially-empty ticket for a same-day cancellation is
        harmless, and adding a new field just to distinguish this
        felt like solving a problem nobody's actually reported yet.
        """
        self.wo.cancel()
        resp = self.client.get(f"/api/work-orders/{self.wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_cannot_access_a_different_organizations_work_order(self):
        other_org = Organization.objects.create(name="Bengkel Lain WO Ticket", invoice_code="BLWT")
        other_customer = Customer.objects.create(organization=other_org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer, plate_number="BP 7001 AA",
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        other_wo = WorkOrder.objects.create(organization=other_org, vehicle=other_vehicle, status="IN_PROGRESS")
        resp = self.client.get(f"/api/work-orders/{other_wo.id}/job-ticket.pdf")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class WorkOrderJobTicketPdfContentTests(APITestCase):
    """
    Unit-level tests against apps.workorders.pdf's own pure functions
    directly — deliberately not going through a full PDF render for
    these, so they don't depend on xhtml2pdf actually being
    installed/working in whatever environment runs them, matching
    the honest "could not be tested end-to-end here" caveat already
    on both pdf.py modules. The one full-render smoke test
    (test_available_once_in_progress_even_without_estimate_origin
    above) still exists to catch a genuinely broken render; these
    exist to prove the specific no-price rule Made was explicit
    about, at the string level where it's cheap and exact to check.
    """

    def test_price_suffix_is_stripped_from_labor_line_description(self):
        from apps.workorders.pdf import _strip_price_suffix
        self.assertEqual(
            _strip_price_suffix("Setel Rem (estimasi Rp 200.000)"), "Setel Rem",
        )

    def test_price_suffix_stripping_is_case_insensitive_and_trims_whitespace(self):
        from apps.workorders.pdf import _strip_price_suffix
        self.assertEqual(
            _strip_price_suffix("Ganti Oli   (ESTIMASI RP 1.500.000)  "), "Ganti Oli",
        )

    def test_description_with_no_price_suffix_is_left_unchanged(self):
        """A direct-entry job line (no Estimate origin) never has this
        suffix at all — must pass through untouched, not stripped of
        real, legitimate text that merely happens to end differently."""
        from apps.workorders.pdf import _strip_price_suffix
        self.assertEqual(_strip_price_suffix("Ganti kampas rem depan"), "Ganti kampas rem depan")

    def test_material_rows_never_include_price_or_subtotal(self):
        """
        The real assertion behind Made's "no prices anywhere on this
        document" rule, checked directly against the rendered HTML
        fragment rather than trusting the Python source not to
        regress — WorkOrderMaterialLine legitimately carries both
        unit_price_at_time and a computed subtotal, and it would be
        an easy, silent mistake to accidentally render one of them
        later while adding some other field.
        """
        from decimal import Decimal
        from unittest.mock import MagicMock

        from apps.workorders.pdf import _material_rows

        line = MagicMock()
        line.part.name = "Kampas Rem"
        line.part.unit = "set"
        line.quantity = Decimal("2.00")
        line.unit_price_at_time = Decimal("250000.00")

        html = _material_rows([line])
        self.assertIn("Kampas Rem", html)
        self.assertIn("2 set", html)
        self.assertNotIn("Rp", html)
        self.assertNotIn("250000", html)
        self.assertNotIn("250.000", html)


class WorkOrderStageTests(WorkOrderAPITestBase):
    """
    Made's own request: a custom, per-repair breakdown of heavy jobs
    into named stages (body work, painting, reassembly, etc.), each
    with its own start/complete timestamps. Deliberately additive —
    confirmed with Chris a routine job never touches this at all,
    proven below alongside the actual stage mechanics.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def _move_wo_to_in_progress(self):
        """
        Direct ORM write, not the status-transition endpoint —
        deliberately, these tests are about stage behavior, not
        re-testing WorkOrderStatusUpdateView itself (that's already
        covered in WorkOrderStartedAtTests). Bypassing the API here
        keeps each test focused on the one thing it's actually
        proving.
        """
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])

    def test_routine_work_order_has_zero_stages_by_default(self):
        """The default, overwhelmingly common case — proven first,
        since this is the behavior that must never regress."""
        self.assertEqual(self.wo.stages.count(), 0)

    def test_create_stage_via_api(self):
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/stages/", {"name": "Body Repair"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["stage"]["name"], "Body Repair")
        self.assertIsNone(resp.data["stage"]["started_at"])
        self.assertIsNone(resp.data["stage"]["completed_at"])

    def test_sequence_defaults_to_next_position_when_omitted(self):
        first = self.client.post(f"/api/work-orders/{self.wo.id}/stages/", {"name": "Body Repair"}, format="json")
        second = self.client.post(f"/api/work-orders/{self.wo.id}/stages/", {"name": "Painting"}, format="json")
        self.assertEqual(first.data["stage"]["sequence"], 1)
        self.assertEqual(second.data["stage"]["sequence"], 2)

    def test_start_sets_timestamp_once(self):
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/start/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data["stage"]["started_at"])

    def test_start_never_overwrites_an_existing_timestamp(self):
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        stage.start()
        stage.save(update_fields=["started_at"])
        original = stage.started_at

        self.client.post(f"/api/work-orders/stages/{stage.id}/start/")
        stage.refresh_from_db()
        self.assertEqual(stage.started_at, original)

    def test_complete_auto_starts_if_never_explicitly_started(self):
        """
        A stage marked complete without ever being explicitly
        started still deserves a real start time on record — better
        a slightly-late timestamp than no record at all for
        something that clearly did happen.

        Now needs a real, done job line first — Chris's own catch,
        4 Aug: completing a stage with nothing checked off underneath
        it is exactly the gap that let "Tune-up: Selesai" sit above
        "Kuras Cairan: Sedang berjalan" in production. See the
        dedicated gate tests just below for that fix's own coverage.
        """
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, stage=stage, description="Ketok panel")
        line.complete()
        line.save(update_fields=["started_at", "completed_at"])
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data["stage"]["started_at"])
        self.assertIsNotNone(resp.data["stage"]["completed_at"])

    def test_cannot_complete_a_stage_with_no_job_lines_at_all(self):
        """
        Chris's own catch, 4 Aug — caught live in production: a stage
        could be marked Selesai while its own job lines underneath
        were still incomplete, or with none at all. A stage with zero
        job lines has nothing to have verified as actually done, same
        reasoning as the WO-level "Ajukan Pemeriksaan" gate.
        """
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        stage.refresh_from_db()
        self.assertIsNone(stage.completed_at)

    def test_cannot_complete_a_stage_while_a_job_line_is_still_unchecked(self):
        """
        The actual regression test for the bug this fixes — a real
        production screenshot showed "Tune-up: Selesai" sitting
        directly above two job lines still reading "Sedang berjalan."
        """
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Tune-up", sequence=1)
        done_line = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=stage, description="Kuras Cairan",
        )
        done_line.complete()
        done_line.save(update_fields=["started_at", "completed_at"])
        in_progress_line = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=stage, description="Pelepasan Komponen",
        )
        in_progress_line.start()
        in_progress_line.save(update_fields=["started_at"])

        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        stage.refresh_from_db()
        self.assertIsNone(stage.completed_at)

    def test_can_complete_a_stage_once_every_job_line_is_genuinely_done(self):
        self._move_wo_to_in_progress()
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Tune-up", sequence=1)
        for desc in ["Kuras Cairan", "Pelepasan Komponen"]:
            line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, stage=stage, description=desc)
            line.complete()
            line.save(update_fields=["started_at", "completed_at"])

        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data["stage"]["completed_at"])

    def test_cannot_start_a_stage_while_work_order_is_still_open(self):
        """
        The actual bug this restriction exists to prevent: without
        it, a stage's own start time could land BEFORE
        WorkOrder.work_started_at, which undermines the entire point
        of a coherent, trustworthy timeline. Confirmed with Chris
        after this exact ordering showed up in real testing.
        """
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        self.assertEqual(self.wo.status, "OPEN")
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/start/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        stage.refresh_from_db()
        self.assertIsNone(stage.started_at)

    def test_complete_cannot_bypass_the_in_progress_requirement(self):
        """
        The loophole this test exists to close: complete() auto-
        starts a never-started stage, so without complete() also
        being blocked, calling it directly on an OPEN WorkOrder would
        silently sidestep the exact restriction test_cannot_start_a_
        stage_while_work_order_is_still_open just proved.

        Needs a real, done job line — otherwise the newer job-lines
        gate (4 Aug) fires first and this test would only be proving
        THAT gate by accident, not the IN_PROGRESS requirement it's
        actually named for. Set directly via the ORM, not
        line.complete() — that method itself requires IN_PROGRESS,
        exactly the state this test deliberately never reaches.
        """
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, stage=stage, description="Ketok panel")
        line.completed_at = timezone.now()
        line.started_at = timezone.now()
        line.save(update_fields=["started_at", "completed_at"])
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/complete/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        stage.refresh_from_db()
        self.assertIsNone(stage.started_at)
        self.assertIsNone(stage.completed_at)

    def test_job_line_can_be_created_directly_under_a_stage(self):
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "Ketok panel pintu", "stage": str(stage.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # str() on both sides deliberately — "stage" is auto-generated
        # by ModelSerializer from the FK (a PrimaryKeyRelatedField),
        # whose to_representation() returns value.pk directly rather
        # than stringifying it. On a UUID-keyed model that stays a
        # real uuid.UUID object in resp.data (the test client's raw
        # Python objects, before JSON rendering) — same class of bug
        # already fixed once for work_order_id elsewhere in this
        # project, just via a different DRF field type this time.
        self.assertEqual(str(resp.data["job_line"]["stage"]), str(stage.id))

    def test_cannot_assign_job_line_to_a_stage_from_a_different_work_order(self):
        """
        The real gap the validate_stage() check exists to close —
        without it, nothing would stop a stray stage id from another
        WorkOrder entirely (even a different vehicle's job) from
        silently attaching here.
        """
        other_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        other_stage = WorkOrderStage.objects.create(organization=self.org, work_order=other_wo, name="Painting", sequence=1)
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "Ketok panel pintu", "stage": str(other_stage.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assign_stage_endpoint_moves_an_existing_job_line(self):
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Ketok panel pintu")
        self.assertIsNone(line.stage)

        resp = self.client.patch(
            f"/api/work-orders/job-lines/{line.id}/assign-stage/", {"stage": str(stage.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        line.refresh_from_db()
        self.assertEqual(line.stage_id, stage.id)

    def test_assign_stage_endpoint_can_clear_it_back_to_unstaged(self):
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Ketok panel pintu", stage=stage)

        resp = self.client.patch(
            f"/api/work-orders/job-lines/{line.id}/assign-stage/", {"stage": None}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        line.refresh_from_db()
        self.assertIsNone(line.stage)

    def test_deleting_a_stage_does_not_delete_its_job_lines(self):
        """
        The core safety property SET_NULL exists for: a job line that
        already happened is real history, and must never vanish just
        because its organizational grouping did.
        """
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        line = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Ketok panel pintu", stage=stage)

        resp = self.client.delete(f"/api/work-orders/stages/{stage.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        line.refresh_from_db()
        self.assertIsNone(line.stage)
        self.assertTrue(WorkOrderJobLine.objects.filter(id=line.id).exists())

    def test_cannot_create_stage_on_a_done_work_order(self):
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/stages/", {"name": "Body Repair"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_cannot_start_a_stage_on_a_cancelled_work_order(self):
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)
        self.wo.cancel()
        resp = self.client.post(f"/api/work-orders/stages/{stage.id}/start/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_stages_scoped_to_organization(self):
        self.client.force_authenticate(user=self.owner)
        stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Body Repair", sequence=1)

        other_org = Organization.objects.create(name="Bengkel Lain Stages", invoice_code="BLS")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherstages@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=other_org, user=other_owner, role="owner", is_active=True)

        self.client.force_authenticate(user=other_owner)
        resp = self.client.get(f"/api/work-orders/stages/{stage.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class SequentialJobLineCascadeTests(WorkOrderAPITestBase):
    """
    Made's own confirmed distinction, 5 Aug: sequential staged work
    (bongkar -> pasang -> uji, one at a time) should flow
    automatically — starting a stage starts its first task, finishing
    one task starts the next. Deliberately a SOFT cascade only
    (Chris's own explicit call): real shop-floor fluidity (a part
    arriving early, work happening out of order) must never be
    blocked by it, and undoing a completed item must never silently
    erase a real timestamp a cascaded sibling already earned.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])
        self.stage = WorkOrderStage.objects.create(organization=self.org, work_order=self.wo, name="Tune-up", sequence=1)
        self.line1 = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=self.stage, description="Kuras Cairan",
        )
        self.line2 = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=self.stage, description="Pelepasan Komponen",
        )
        self.line3 = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, stage=self.stage, description="Pemasangan Kembali",
        )

    def test_starting_a_stage_auto_starts_its_first_job_line_only(self):
        self.stage.start()
        self.stage.save(update_fields=["started_at"])
        self.line1.refresh_from_db()
        self.line2.refresh_from_db()
        self.assertIsNotNone(self.line1.started_at)
        self.assertIsNone(self.line2.started_at)

    def test_completing_a_job_line_auto_starts_the_next_sibling(self):
        self.line1.start()
        self.line1.save(update_fields=["started_at"])
        self.line1.complete()
        self.line1.save(update_fields=["completed_at"])
        self.line2.refresh_from_db()
        self.line3.refresh_from_db()
        self.assertIsNotNone(self.line2.started_at)
        self.assertIsNone(self.line2.completed_at)
        self.assertIsNone(self.line3.started_at)

    def test_cascade_never_touches_unstaged_job_lines(self):
        """Made's own explicit distinction: only genuinely sequential,
        staged work cascades — parallel, independent items stay
        exactly as they already behave."""
        unstaged_a = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Ganti Oli")
        unstaged_b = WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Cek Ban")
        unstaged_a.complete()
        unstaged_a.save(update_fields=["started_at", "completed_at"])
        unstaged_b.refresh_from_db()
        self.assertIsNone(unstaged_b.started_at)

    def test_soft_cascade_does_not_block_starting_a_later_item_out_of_order(self):
        """The actual point of keeping this soft, Chris's own explicit
        call: real shop-floor fluidity — a part arrives early, work
        genuinely happens out of order — must never be blocked."""
        self.line3.start()
        self.line3.save(update_fields=["started_at"])
        self.line1.refresh_from_db()
        self.line2.refresh_from_db()
        self.assertIsNotNone(self.line3.started_at)
        self.assertIsNone(self.line1.started_at)
        self.assertIsNone(self.line2.started_at)

    def test_undo_never_reverts_a_cascaded_siblings_real_timestamp(self):
        """Chris's own explicit call: real timestamps a cascaded
        sibling already earned must never be silently erased just
        because the item that triggered them got reset."""
        self.line1.start()
        self.line1.save(update_fields=["started_at"])
        self.line1.complete()
        self.line1.save(update_fields=["completed_at"])
        self.line2.refresh_from_db()
        line2_started_at = self.line2.started_at
        self.assertIsNotNone(line2_started_at)

        self.line1.reset()
        self.line1.save(update_fields=["started_at", "completed_at"])
        self.line2.refresh_from_db()
        self.assertEqual(self.line2.started_at, line2_started_at)

    def test_cascade_via_the_real_toggle_endpoint_end_to_end(self):
        """Same real chain, but through the actual API a mechanic
        clicks — not just the model methods directly."""
        first_toggle = self.client.patch(f"/api/work-orders/job-lines/{self.line1.id}/toggle/")
        self.assertEqual(first_toggle.status_code, status.HTTP_200_OK)
        second_toggle = self.client.patch(f"/api/work-orders/job-lines/{self.line1.id}/toggle/")
        self.assertTrue(second_toggle.data["job_line"]["is_done"])

        self.line2.refresh_from_db()
        self.assertIsNotNone(self.line2.started_at)


class WorkOrderIsOverdueTests(WorkOrderAPITestBase):
    """
    Made's own literal example from the 28 Jul meeting: an oil
    change + brake pads taking more than 2 hours.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_open_work_order_is_never_overdue(self):
        self.assertFalse(self.wo.is_overdue)

    def test_in_progress_but_no_work_started_at_is_not_overdue(self):
        """
        A direct-entry WO (no Estimate origin) never gets
        work_started_at populated at all, even once IN_PROGRESS —
        can't be "overdue" against a duration that was never
        captured in the first place.
        """
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])
        self.assertFalse(self.wo.is_overdue)

    def test_in_progress_recently_started_is_not_yet_overdue(self):
        self.wo.status = "IN_PROGRESS"
        self.wo.work_started_at = timezone.now() - timedelta(minutes=30)
        self.wo.save(update_fields=["status", "work_started_at"])
        self.assertFalse(self.wo.is_overdue)

    def test_in_progress_past_threshold_is_overdue(self):
        self.wo.status = "IN_PROGRESS"
        self.wo.work_started_at = timezone.now() - timedelta(hours=3)
        self.wo.save(update_fields=["status", "work_started_at"])
        self.assertTrue(self.wo.is_overdue)

    def test_done_work_order_is_never_overdue_even_after_a_long_time(self):
        self.wo.status = "IN_PROGRESS"
        self.wo.work_started_at = timezone.now() - timedelta(hours=10)
        self.wo.status = "DONE"
        self.wo.save(update_fields=["status", "work_started_at"])
        self.assertFalse(self.wo.is_overdue)


class WorkOrderStageIsOverdueTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_not_started_is_not_overdue(self):
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Body Repair", sequence=1,
        )
        self.assertFalse(stage.is_overdue)

    def test_uses_default_threshold_when_no_override_set(self):
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=3),
        )
        self.assertTrue(stage.is_overdue)

    def test_expected_duration_override_prevents_false_alarm_on_heavy_stage(self):
        """
        The actual reason expected_duration_hours exists: a genuinely
        heavy stage (body repair) legitimately takes longer than the
        generic 2-hour default without being a real problem.
        """
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=3),
            expected_duration_hours=Decimal("8.0"),
        )
        self.assertFalse(stage.is_overdue)

    def test_completed_stage_is_never_overdue(self):
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=10),
            completed_at=timezone.now(),
        )
        self.assertFalse(stage.is_overdue)


class MechanicAPITests(WorkOrderAPITestBase):

    def test_create_and_list_mechanic(self):
        resp = self.client.post("/api/mechanics/", {"name": "Alex"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["mechanic"]["is_active"])

        listing = self.client.get("/api/mechanics/")
        self.assertEqual(listing.data["count"], 1)

    def test_deactivate_via_put_not_delete(self):
        """
        No DELETE endpoint exists for Mechanic at all, on purpose —
        see the model's own docstring. Deactivation via this same PUT
        is the only removal path.
        """
        mechanic = Mechanic.objects.create(organization=self.org, name="Wira")
        resp = self.client.put(f"/api/mechanics/{mechanic.id}/", {"is_active": False}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mechanic.refresh_from_db()
        self.assertFalse(mechanic.is_active)

    def test_no_delete_method_exists(self):
        mechanic = Mechanic.objects.create(organization=self.org, name="Wira")
        resp = self.client.delete(f"/api/mechanics/{mechanic.id}/")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class WorkOrderStageAssignmentTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Body Repair", sequence=1,
        )
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Alex")

    def test_assign_mechanic_via_put(self):
        resp = self.client.put(
            f"/api/work-orders/stages/{self.stage.id}/",
            {"assigned_to": str(self.mechanic.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["stage"]["assigned_to_name"], "Alex")

    def test_set_expected_duration_via_put(self):
        resp = self.client.put(
            f"/api/work-orders/stages/{self.stage.id}/",
            {"expected_duration_hours": "8.0"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(resp.data["stage"]["expected_duration_hours"]), Decimal("8.0"))

    def test_cannot_assign_mechanic_from_a_different_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Mekanik", invoice_code="BLM")
        other_mechanic = Mechanic.objects.create(organization=other_org, name="Orang Asing")
        resp = self.client.put(
            f"/api/work-orders/stages/{self.stage.id}/",
            {"assigned_to": str(other_mechanic.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivating_a_mechanic_does_not_delete_historical_assignment(self):
        self.stage.assigned_to = self.mechanic
        self.stage.save(update_fields=["assigned_to"])
        self.mechanic.is_active = False
        self.mechanic.save(update_fields=["is_active"])

        self.stage.refresh_from_db()
        self.assertEqual(self.stage.assigned_to_id, self.mechanic.id)


class DashboardSummaryTests(WorkOrderAPITestBase):
    """
    The real deliverable of this whole round — proves the aggregation
    endpoint actually answers Made's four numbered requirements
    correctly, not just that it returns 200.
    """

    def test_mechanics_active_and_working_counts(self):
        Mechanic.objects.create(organization=self.org, name="Alex")
        Mechanic.objects.create(organization=self.org, name="Samsut")
        Mechanic.objects.create(organization=self.org, name="Yayu", is_active=False)
        working_mechanic = Mechanic.objects.create(organization=self.org, name="Wira")

        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            assigned_to=working_mechanic, started_at=timezone.now(),
        )

        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # 3 active (Alex, Samsut, Wira) — Yayu is inactive, excluded:
        self.assertEqual(resp.data["mechanics"]["active"], 3)
        self.assertEqual(resp.data["mechanics"]["working"], 1)

    def test_working_mechanic_not_double_counted_across_parallel_stages(self):
        """
        The same mechanic assigned to two different in-progress
        stages, even across different WorkOrders, must only count
        once — exactly what .distinct() at the DB level exists to
        guarantee.
        """
        mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        wo1 = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        wo2 = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo1, name="Body Repair", sequence=1,
            assigned_to=mechanic, started_at=timezone.now(),
        )
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo2, name="Painting", sequence=1,
            assigned_to=mechanic, started_at=timezone.now(),
        )
        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.data["mechanics"]["working"], 1)

    def test_queued_vs_in_progress_split(self):
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)  # OPEN
        wo2 = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        wo2.status = "IN_PROGRESS"
        wo2.save(update_fields=["status"])

        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.data["work_orders"]["queued"], 1)
        self.assertEqual(resp.data["work_orders"]["in_progress"], 1)

    def test_vehicles_cleared_counts_only_done_work_orders_in_period(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self._ready_to_close(wo)
        wo.close(closed_by=self.owner)

        resp = self.client.get("/api/dashboard/summary/?period=today")
        self.assertEqual(resp.data["vehicles_cleared"]["count"], 1)
        self.assertEqual(resp.data["vehicles_cleared"]["period"], "today")

    def test_overdue_work_orders_list_contains_the_real_overdue_one(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        wo.status = "IN_PROGRESS"
        wo.work_started_at = timezone.now() - timedelta(hours=3)
        wo.save(update_fields=["status", "work_started_at"])

        not_overdue = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        not_overdue.status = "IN_PROGRESS"
        not_overdue.work_started_at = timezone.now() - timedelta(minutes=10)
        not_overdue.save(update_fields=["status", "work_started_at"])

        resp = self.client.get("/api/dashboard/summary/")
        overdue_ids = [item["id"] for item in resp.data["overdue"]["work_orders"]]
        self.assertIn(str(wo.id), overdue_ids)
        self.assertNotIn(str(not_overdue.id), overdue_ids)

    def test_overdue_stages_list_respects_expected_duration_override(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=3), expected_duration_hours=Decimal("8.0"),
        )
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Oli Mesin", sequence=2,
            started_at=timezone.now() - timedelta(hours=3),
        )

        resp = self.client.get("/api/dashboard/summary/")
        overdue_names = [item["name"] for item in resp.data["overdue"]["stages"]]
        self.assertNotIn("Body Repair", overdue_names)  # covered by its own override
        self.assertIn("Oli Mesin", overdue_names)        # falls back to the 2h default

    def test_overdue_stage_exposes_the_real_work_order_id_not_just_its_number(self):
        """
        Caught before shipping, not after: an overdue stage entry
        must carry the WorkOrder's real UUID, not only its human
        number — without it, the frontend has no way to actually
        link back to the real work order at all, and would silently
        construct a broken link using the stage's own id instead.
        """
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=3),
        )
        resp = self.client.get("/api/dashboard/summary/")
        entry = next(item for item in resp.data["overdue"]["stages"] if item["id"] == str(stage.id))
        self.assertEqual(entry["work_order_id"], str(wo.id))
        self.assertNotEqual(entry["work_order_id"], entry["id"])

    def test_summary_scoped_to_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Dashboard", invoice_code="BLD")
        Mechanic.objects.create(organization=other_org, name="Orang Asing")

        resp = self.client.get("/api/dashboard/summary/")
        self.assertEqual(resp.data["mechanics"]["active"], 0)


class ActiveJobsViewTests(WorkOrderAPITestBase):
    """
    B2 in the sprint review — a full roster of everything currently
    in motion, not just the overdue subset the Owner Dashboard's own
    summary already surfaces.
    """

    def test_only_open_status_work_orders_appear(self):
        open_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        done_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self._ready_to_close(done_wo)
        done_wo.close(closed_by=self.owner)
        cancelled_wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        cancelled_wo.cancel()

        resp = self.client.get("/api/work-orders/active/")
        ids = [r["id"] for r in resp.data["results"]]
        self.assertIn(str(open_wo.id), ids)
        self.assertNotIn(str(done_wo.id), ids)
        self.assertNotIn(str(cancelled_wo.id), ids)

    def test_current_stage_is_the_one_started_but_not_completed(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        completed_stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            started_at=timezone.now() - timedelta(hours=5), completed_at=timezone.now() - timedelta(hours=2),
        )
        in_motion_stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Painting", sequence=2,
            assigned_to=mechanic, started_at=timezone.now() - timedelta(hours=1),
        )
        not_started_stage = WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Reassembly", sequence=3,
        )

        resp = self.client.get("/api/work-orders/active/")
        entry = next(r for r in resp.data["results"] if r["id"] == str(wo.id))
        self.assertEqual(entry["current_stage_name"], "Painting")
        self.assertEqual(entry["current_stage_mechanic"], "Alex")

    def test_no_current_stage_for_a_routine_work_order_with_no_stages(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        resp = self.client.get("/api/work-orders/active/")
        entry = next(r for r in resp.data["results"] if r["id"] == str(wo.id))
        self.assertIsNone(entry["current_stage_name"])
        self.assertIsNone(entry["current_stage_mechanic"])

    def test_current_stage_mechanic_is_none_when_stage_unassigned(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            started_at=timezone.now(),
        )
        resp = self.client.get("/api/work-orders/active/")
        entry = next(r for r in resp.data["results"] if r["id"] == str(wo.id))
        self.assertEqual(entry["current_stage_name"], "Body Repair")
        self.assertIsNone(entry["current_stage_mechanic"])

    def test_elapsed_since_prefers_work_started_at_over_created_at(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        wo.status = "IN_PROGRESS"
        wo.work_started_at = timezone.now() - timedelta(hours=4)
        wo.save(update_fields=["status", "work_started_at"])

        resp = self.client.get("/api/work-orders/active/")
        entry = next(r for r in resp.data["results"] if r["id"] == str(wo.id))
        self.assertAlmostEqual(entry["elapsed_hours"], 4.0, delta=0.1)

    def test_results_sorted_longest_waiting_first(self):
        recent = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        recent.status = "IN_PROGRESS"
        recent.work_started_at = timezone.now() - timedelta(minutes=10)
        recent.save(update_fields=["status", "work_started_at"])

        old = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        old.status = "IN_PROGRESS"
        old.work_started_at = timezone.now() - timedelta(hours=6)
        old.save(update_fields=["status", "work_started_at"])

        resp = self.client.get("/api/work-orders/active/")
        ids_in_order = [r["id"] for r in resp.data["results"]]
        self.assertLess(ids_in_order.index(str(old.id)), ids_in_order.index(str(recent.id)))

    def test_scoped_to_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Active Jobs", invoice_code="BLAJ")
        other_customer = Customer.objects.create(organization=other_org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer, plate_number="X 1 XX",
            model="Test", manufacture_year=2020,
        )
        WorkOrder.objects.create(organization=other_org, vehicle=other_vehicle)

        resp = self.client.get("/api/work-orders/active/")
        self.assertEqual(resp.data["count"], 0)


class WorkOrderMechanicAssignmentTests(WorkOrderAPITestBase):
    """
    Made's own explicit reason, confirmed 31 Jul: a specific mechanic
    must be identifiable on every job, even routine work, so he can
    go back and question that person directly if the same car has an
    issue again. Distinct from WorkOrderStage's own assigned_to,
    tested separately elsewhere — this is the single mechanic
    responsible for a job as a whole, not per-stage.
    """

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Alex")

    def test_assign_mechanic_via_put(self):
        resp = self.client.put(
            f"/api/work-orders/{self.wo.id}/", {"assigned_to": str(self.mechanic.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["work_order"]["assigned_to_name"], "Alex")

    def test_cannot_assign_mechanic_from_a_different_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain WO Mekanik", invoice_code="BLWM")
        other_mechanic = Mechanic.objects.create(organization=other_org, name="Orang Asing")
        resp = self.client.put(
            f"/api/work-orders/{self.wo.id}/", {"assigned_to": str(other_mechanic.id)}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivating_a_mechanic_does_not_delete_historical_assignment(self):
        """
        Same SET_NULL-vs-deactivate reasoning already proven for
        WorkOrderStage.assigned_to — a mechanic leaving the roster
        must never silently erase who actually worked a real job.
        """
        self.wo.assigned_to = self.mechanic
        self.wo.save(update_fields=["assigned_to"])
        self.mechanic.is_active = False
        self.mechanic.save(update_fields=["is_active"])

        self.wo.refresh_from_db()
        self.assertEqual(self.wo.assigned_to_id, self.mechanic.id)

    def test_unset_via_null(self):
        self.wo.assigned_to = self.mechanic
        self.wo.save(update_fields=["assigned_to"])
        resp = self.client.put(f"/api/work-orders/{self.wo.id}/", {"assigned_to": None}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["work_order"]["assigned_to"])
