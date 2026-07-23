# =============================================================================
# === backend/apps/workorders/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.inventory.models import Part, PartUsage, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from rest_framework import status
from rest_framework.test import APITestCase, APITransactionTestCase

from .models import WorkOrder, WorkOrderJobLine, WorkOrderMaterialLine


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


class WorkOrderNumberingTests(WorkOrderAPITestBase):

    def test_number_is_plain_sequential_no_prefix(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["work_order"]["number"], "1")
        self.assertEqual(resp.data["work_order"]["sequence_number"], 1)

    def test_sequence_increments_and_does_not_reset(self):
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(first.data["work_order"]["sequence_number"], 1)
        self.assertEqual(second.data["work_order"]["sequence_number"], 2)


class WorkOrderJobLineTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_create_and_toggle_job_line(self):
        create = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "Bak belakang las reparasi"}, format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertFalse(create.data["job_line"]["is_done"])

        line_id = create.data["job_line"]["id"]
        toggle = self.client.patch(f"/api/work-orders/job-lines/{line_id}/toggle/")
        self.assertEqual(toggle.status_code, status.HTTP_200_OK)
        self.assertTrue(toggle.data["job_line"]["is_done"])

    def test_cannot_add_job_line_to_cancelled_work_order(self):
        self.wo.status = "CANCELLED"
        self.wo.save(update_fields=["status"])
        resp = self.client.post(
            f"/api/work-orders/{self.wo.id}/job-lines/",
            {"description": "x"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


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

    def test_service_record_created_by_close_can_still_be_invoiced_normally(self):
        """
        The whole point of freezing into a real ServiceRecord — proves
        the Sprint 2 invoicing flow works completely unmodified
        against a WorkOrder-originated record.
        """
        from apps.invoicing.models import Invoice
        record = self.wo.close(closed_by=self.owner)
        invoice = Invoice.objects.create(service_record=record, created_by=self.owner)
        self.assertEqual(invoice.line_items.count(), 0)  # created directly, no line items added here
        self.assertTrue(invoice.number.startswith("INV/REG/AM/"))


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
        self.client.force_authenticate(user=self.owner)

    def test_create_work_order_via_real_http_request_without_implicit_transaction(self):
        resp = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["work_order"]["number"], "1")

    def test_second_work_order_gets_next_sequence_via_real_http_requests(self):
        first = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        second = self.client.post(f"/api/vehicles/{self.vehicle.id}/work-orders/", {}, format="json")
        self.assertEqual(first.data["work_order"]["sequence_number"], 1)
        self.assertEqual(second.data["work_order"]["sequence_number"], 2)
