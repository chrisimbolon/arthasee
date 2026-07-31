# =============================================================================
# === backend/apps/invoicing/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.inventory.models import Part, PartUsage, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Invoice, InvoiceSequence


class InvoicingAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.invoicing@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 2219 AB", manufacture_year=2022,
            vehicle_type="Mobil", model="Honda Brio",
        )
        # Made's own explicit reason, confirmed 31 Jul: a specific
        # mechanic must be identifiable on every invoice, even for
        # routine work, so he can go back and question that person
        # directly if the same car has an issue again. self.service_
        # record is now created through a real WorkOrder.close() call
        # — the only way a ServiceRecord ever actually comes into
        # existence in production — with a mechanic already assigned,
        # so every existing test in this file that creates an invoice
        # from it keeps working exactly as before.
        # InvoiceMechanicRequirementTests below deliberately builds
        # its own service records without a mechanic, specifically to
        # prove the hard block itself.
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic,
        )
        self.service_record = work_order.close(closed_by=self.owner)
        self.part = Part.objects.create(
            organization=self.org, name="Kampas Rem", unit="set", unit_price=Decimal("250000.00"),
        )
        StockAdjustment.objects.create(
            organization=self.org, part=self.part, quantity_change=Decimal("10.00"), reason="restock",
        )
        self.client.force_authenticate(user=self.owner)


class InvoiceCreationTests(InvoicingAPITestBase):

    def test_create_invoice_snapshots_customer_and_plate(self):
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["invoice"]["customer_name_snapshot"], "Brian Sira")
        self.assertEqual(resp.data["invoice"]["license_plate_snapshot"], "BP 2219 AB")

    def test_create_invoice_pulls_in_existing_part_usage(self):
        PartUsage.objects.create(
            organization=self.org, service_record=self.service_record, part=self.part,
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("250000.00"),
        )
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        line_items = resp.data["invoice"]["line_items"]
        self.assertEqual(len(line_items), 1)
        self.assertEqual(line_items[0]["kind"], "part")
        self.assertEqual(Decimal(line_items[0]["unit_price"]), Decimal("250000.00"))

    def test_create_invoice_with_multiple_labor_lines(self):
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {
                "labor_lines": [
                    {"description": "Jasa Servis Rem", "quantity": 1, "unit_price": 150000},
                    {"description": "Jasa Balancing", "quantity": 1, "unit_price": 75000},
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        labor_items = [li for li in resp.data["invoice"]["line_items"] if li["kind"] == "labor"]
        self.assertEqual(len(labor_items), 2)
        self.assertEqual(Decimal(resp.data["invoice"]["total"]), Decimal("225000.00"))

    def test_price_snapshot_survives_later_part_price_change(self):
        """
        The core reason InvoiceLineItem snapshots unit_price instead
        of reading Part.unit_price live — this is the test that
        would fail immediately if that discipline were ever dropped.
        """
        PartUsage.objects.create(
            organization=self.org, service_record=self.service_record, part=self.part,
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("250000.00"),
        )
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = resp.data["invoice"]["id"]

        self.part.unit_price = Decimal("999999.00")
        self.part.save(update_fields=["unit_price"])

        recheck = self.client.get(f"/api/invoices/{invoice_id}/")
        self.assertEqual(Decimal(recheck.data["invoice"]["total"]), Decimal("250000.00"))

    def test_cannot_invoice_the_same_service_record_twice(self):
        first = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Invoice.objects.filter(service_record=self.service_record).count(), 1)

    def test_deposit_reduces_balance_due(self):
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa", "quantity": 1, "unit_price": 100000}]},
            format="json",
        )
        invoice = Invoice.objects.get(id=resp.data["invoice"]["id"])
        invoice.deposit_amount = Decimal("40000.00")
        invoice.save(update_fields=["deposit_amount"])
        self.assertEqual(invoice.balance_due, Decimal("60000.00"))

    def test_missing_invoice_code_returns_clean_400_not_500(self):
        """
        The actual bug this guards against: Invoice.save() used to
        hardcode 'AM' directly, so a shop with no invoice_code
        configured would silently collide with Arya Motor's numbers
        instead of getting told to configure their own code.
        """
        self.org.invoice_code = ""
        self.org.save(update_fields=["invoice_code"])
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("invoice_code", resp.data["message"])
        # The atomic transaction must have rolled back completely —
        # no orphaned Invoice or InvoiceLineItem left behind by the
        # failed attempt.
        self.assertFalse(Invoice.objects.filter(service_record=self.service_record).exists())


class InvoiceNumberingTests(InvoicingAPITestBase):

    def _create_invoice_for_new_visit(self, plate):
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number=plate, manufacture_year=2022,
            vehicle_type="Mobil", model="Honda Brio",
        )
        # Reuses self.mechanic from the base fixture — same real
        # WorkOrder.close() pattern, not a directly-created
        # ServiceRecord with no originating WorkOrder.
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=vehicle, assigned_to=self.mechanic,
        )
        record = work_order.close(closed_by=self.owner)
        return self.client.post(f"/api/service-records/{record.id}/invoice/", {}, format="json")

    def test_sequence_increments_within_the_same_year(self):
        first = self._create_invoice_for_new_visit("BP 0001 AA")
        second = self._create_invoice_for_new_visit("BP 0002 AA")
        self.assertEqual(first.data["invoice"]["sequence_number"], 1)
        self.assertEqual(second.data["invoice"]["sequence_number"], 2)

    def test_number_format_matches_mades_scheme(self):
        resp = self._create_invoice_for_new_visit("BP 0003 AA")
        number = resp.data["invoice"]["number"]
        self.assertRegex(number, r"^INV/REG/AM/\d{4}/\d{4}$")

    def test_sequence_is_scoped_per_organization(self):
        """Two different shops both creating their first invoice of
        the year must both legitimately get sequence 1 — the
        (organization, year) scoping on InvoiceSequence is what makes
        that safe rather than a collision."""
        self._create_invoice_for_new_visit("BP 0004 AA")  # org's 2nd invoice this test class

        other_org = Organization.objects.create(name="Bengkel Lain Invoicing", invoice_code="BL")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherinvoicing@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=other_org, user=other_owner, role="owner", is_active=True,
        )
        other_customer = Customer.objects.create(organization=other_org, name="Other Customer")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer,
            plate_number="BP 9999 ZZ", manufacture_year=2022,
            vehicle_type="Mobil", model="Other Car",
        )
        # A mechanic scoped to other_org specifically, not self.mechanic
        # (which belongs to self.org) — a real WorkOrder's mechanic
        # must belong to the same organization as the WorkOrder itself.
        other_mechanic = Mechanic.objects.create(organization=other_org, name="Budi")
        other_work_order = WorkOrder.objects.create(
            organization=other_org, vehicle=other_vehicle, assigned_to=other_mechanic,
        )
        other_record = other_work_order.close(closed_by=other_owner)
        self.client.force_authenticate(user=other_owner)
        resp = self.client.post(f"/api/service-records/{other_record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.data["invoice"]["sequence_number"], 1)


class InvoiceStatusTests(InvoicingAPITestBase):

    def test_status_can_be_updated(self):
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = resp.data["invoice"]["id"]
        update = self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json")
        self.assertEqual(update.status_code, status.HTTP_200_OK)
        self.assertEqual(update.data["invoice"]["status"], "ISSUED")

    def test_invalid_status_rejected(self):
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = resp.data["invoice"]["id"]
        update = self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "MADE_UP"}, format="json")
        self.assertEqual(update.status_code, status.HTTP_400_BAD_REQUEST)


class InvoiceTenantIsolationTests(InvoicingAPITestBase):

    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Bengkel Lain Invoice Isolasi")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherinvoiceisolasi@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_create_invoice_for_org_a_service_record(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_b_cannot_view_org_a_invoice(self):
        created = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = created.data["invoice"]["id"]
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/invoices/{invoice_id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class InvoicePdfTests(InvoicingAPITestBase):
    """
    Made's own ask, 31 Jul: a real, downloadable PDF for LUNAS
    invoices, gated hard to PAID only — confirmed with Chris. Can't
    verify individual rendered cell values the way the Excel-based
    tests do (no PDF-parsing library available here), so this proves
    what's genuinely checkable: the actual gate itself (the real
    point of this feature), that a real, valid PDF comes back for a
    PAID invoice, and that the filename is safe.
    """

    def _create_and_pay(self):
        create = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Servis Rem", "quantity": 1, "unit_price": 150000}]},
            format="json",
        )
        invoice_id = create.data["invoice"]["id"]
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json")
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "PAID"}, format="json")
        return invoice_id

    def test_returns_a_real_pdf_for_a_paid_invoice(self):
        invoice_id = self._create_and_pay()
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        # %PDF is the real, standard magic-byte signature every valid
        # PDF file starts with — proves this is a genuine rendered
        # document, not empty or garbage bytes silently returned as
        # a 200.
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_blocked_for_draft_invoice(self):
        create = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = create.data["invoice"]["id"]
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Lunas", resp.data["message"])

    def test_blocked_for_issued_invoice(self):
        create = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = create.data["invoice"]["id"]
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json")
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_blocked_for_cancelled_invoice(self):
        create = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = create.data["invoice"]["id"]
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "CANCELLED"}, format="json")
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_filename_has_no_raw_slashes(self):
        """
        The exact real bug caught before shipping: invoice.number
        genuinely contains slashes ("INV/REG/AM/0004/2026"), which
        would break as a raw filename on a real filesystem.
        """
        invoice_id = self._create_and_pay()
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        disposition = resp["Content-Disposition"]
        filename = disposition.split("filename=")[1]
        self.assertNotIn("/", filename)

    def test_org_b_cannot_download_org_a_invoice_pdf(self):
        """
        other_owner isn't part of InvoicingAPITestBase's own setUp()
        — only InvoiceTenantIsolationTests defines it, in its own
        setUp(), for a different test class entirely. Created locally
        here instead, matching the same self-contained pattern
        InvoiceNumberingTests.test_sequence_is_scoped_per_organization
        already uses for exactly this situation.
        """
        invoice_id = self._create_and_pay()

        other_org = Organization.objects.create(name="Bengkel Lain PDF", invoice_code="BLP")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherinvoicepdf@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=other_org, user=other_owner, role="owner", is_active=True,
        )

        self.client.force_authenticate(user=other_owner)
        resp = self.client.get(f"/api/invoices/{invoice_id}/receipt.pdf")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class InvoiceMechanicRequirementTests(InvoicingAPITestBase):
    """
    Made's own explicit reason, confirmed 31 Jul: a specific mechanic
    must be identifiable on every invoice, even for routine work, so
    he can go back and question that person directly if the same car
    has an issue again. Hard-blocked, not a soft warning — deliberately
    builds its own service records WITHOUT a mechanic assigned, since
    the shared base fixture's own self.service_record now always has
    one (see InvoicingAPITestBase's own setUp() for why).
    """

    def _work_order_without_mechanic(self):
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        return work_order.close(closed_by=self.owner)

    def test_cannot_create_invoice_when_work_order_has_no_mechanic(self):
        record = self._work_order_without_mechanic()
        resp = self.client.post(f"/api/service-records/{record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mekanik", resp.data["message"].lower())

    def test_failed_attempt_leaves_no_orphaned_invoice(self):
        """Same rollback discipline already proven for the missing-
        invoice_code case — a failed attempt must leave nothing
        behind, not a half-created Invoice with no line items."""
        record = self._work_order_without_mechanic()
        self.client.post(f"/api/service-records/{record.id}/invoice/", {}, format="json")
        self.assertFalse(Invoice.objects.filter(service_record=record).exists())

    def test_cannot_create_invoice_when_service_record_has_no_work_order_at_all(self):
        """
        Defensive edge case — a ServiceRecord created some other way
        (direct ORM, an admin action, a future code path) with no
        WorkOrder pointing back to it at all. getattr(..., None) must
        treat this exactly the same as "no mechanic assigned," not
        crash with RelatedObjectDoesNotExist.
        """
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-31", odometer_km=5000,
            issue_description="Dibuat langsung, tanpa work order",
        )
        resp = self.client.post(f"/api/service-records/{record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_create_invoice_once_mechanic_is_assigned(self):
        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic,
        )
        record = work_order.close(closed_by=self.owner)
        resp = self.client.post(f"/api/service-records/{record.id}/invoice/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["invoice"]["mechanic_name_snapshot"], "Alex")

    def test_mechanic_snapshot_survives_later_mechanic_rename(self):
        """
        The core reason this is a snapshot rather than a live
        reference — mirrors test_price_snapshot_survives_later_
        part_price_change's own reasoning exactly, applied to the
        mechanic's name instead of a part's price.
        """
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = resp.data["invoice"]["id"]

        self.mechanic.name = "Alex (Nama Baru)"
        self.mechanic.save(update_fields=["name"])

        recheck = self.client.get(f"/api/invoices/{invoice_id}/")
        self.assertEqual(recheck.data["invoice"]["mechanic_name_snapshot"], "Alex")

    def test_mechanic_snapshot_survives_later_mechanic_deactivation(self):
        resp = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = resp.data["invoice"]["id"]

        self.mechanic.is_active = False
        self.mechanic.save(update_fields=["is_active"])

        recheck = self.client.get(f"/api/invoices/{invoice_id}/")
        self.assertEqual(recheck.data["invoice"]["mechanic_name_snapshot"], "Alex")
