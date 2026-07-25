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
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{self.vehicle.id}/estimates/", {}, format="json")
        self.assertEqual(first.data["estimate"]["sequence_number"], 1)
        self.assertEqual(second.data["estimate"]["sequence_number"], 2)


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
