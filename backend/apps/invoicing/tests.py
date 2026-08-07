# =============================================================================
# === backend/apps/invoicing/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.inventory.models import Part, PartUsage, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderJobLine
from django.test import SimpleTestCase
from django.utils import timezone
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
        # Made's own confirmed real-world rule, 2 Aug — Chris
        # witnessed it directly at Arya Motor: EVERY job goes through
        # QC before being marked done, even a routine oil change or
        # spark plug replacement. WorkOrder.close() now correctly
        # rejects closing directly from OPEN or IN_PROGRESS (see
        # apps.workorders.models.WorkOrder.close()) — a real
        # precondition, not test boilerplate to skip.
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
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
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
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
        other_work_order.status = "IN_PROGRESS"
        other_work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=other_org, work_order=other_work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        other_work_order.status = "QC"
        other_work_order.save(update_fields=["status"])
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

class InvoiceIssuedEventTests(InvoicingAPITestBase):
    """
    Proves both halves of what changed in InvoiceStatusUpdateView:
    the real InvoiceIssued publish with a correct revenue split, and
    the DRAFT one-way guard that's what makes "exactly once" an
    actual guarantee for that publish, not just an intention.
    """

    def _issued_invoice(self):
        """
        One part line (via PartUsage, quantity 1.00 @ self.part's
        250000.00) + one labor line (quantity 1 @ 100000) — real
        split across both revenue categories, not a same-category
        coincidence that would pass even with the fields swapped.
        """
        PartUsage.objects.create(
            organization=self.org, service_record=self.service_record, part=self.part,
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("250000.00"),
        )
        create = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Servis Rem", "quantity": 1, "unit_price": 100000}]},
            format="json",
        )
        return create.data["invoice"]["id"]

    def test_issuing_invoice_publishes_invoice_issued_with_correct_split(self):
        invoice_id = self._issued_invoice()

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(
                f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        row = Outbox.objects.get(event_type="InvoiceIssued", payload__invoice_id=invoice_id)
        self.assertEqual(row.organization_id, self.org.id)
        # 1.00 * 100000.00 (labor) and 1.00 * 250000.00 (part) —
        # verified by hand before writing this assertion, see
        # conversation for the standalone check.
        self.assertEqual(row.payload["service_amount"], "100000.0000")
        self.assertEqual(row.payload["parts_amount"], "250000.0000")
        self.assertEqual(row.payload["total"], "350000.0000")
        self.assertEqual(row.payload["line_item_count"], 2)
        self.assertEqual(row.status, Outbox.Status.PROCESSED)

    def test_creating_invoice_alone_does_not_publish_invoice_issued(self):
        """
        The trigger is specifically the DRAFT -> ISSUED transition,
        not invoice creation itself — an invoice sits in DRAFT the
        moment it's created (see Invoice.STATUS_CHOICES default) and
        must not recognize revenue before it's actually issued.
        """
        self._issued_invoice()  # creates but never PATCHes to ISSUED
        self.assertEqual(Outbox.objects.filter(event_type="InvoiceIssued").count(), 0)

    def test_cannot_revert_issued_invoice_to_draft(self):
        invoice_id = self._issued_invoice()
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json")

        resp = self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "DRAFT"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        invoice = Invoice.objects.get(id=invoice_id)
        self.assertEqual(invoice.status, "ISSUED")  # unchanged by the rejected attempt
        # Exactly one InvoiceIssued — the guard blocks the illegal
        # revert outright, it isn't merely suppressing a second
        # publish while quietly allowing the revert itself through.
        self.assertEqual(
            Outbox.objects.filter(event_type="InvoiceIssued", payload__invoice_id=invoice_id).count(), 1,
        )

    def test_cannot_revert_cancelled_invoice_to_draft(self):
        create = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = create.data["invoice"]["id"]
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "CANCELLED"}, format="json")

        resp = self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "DRAFT"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_draft_to_draft_is_still_allowed(self):
        """
        Precision check on the guard — it blocks a REAL reversion
        (old_status != DRAFT), not every PATCH that merely names
        DRAFT as the target. A same-state no-op must still succeed.
        """
        create = self.client.post(f"/api/service-records/{self.service_record.id}/invoice/", {}, format="json")
        invoice_id = create.data["invoice"]["id"]

        resp = self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "DRAFT"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

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
        """
        UPDATED — status="PAID" can no longer be reached via a manual
        PATCH (see apps.invoicing.views.InvoiceStatusUpdateView's own
        updated docstring, and apps.payments.models.Payment.record()).
        This now pays the invoice for real through the actual payment
        endpoint, same as production — the second PATCH this used to
        end with is exactly the shortcut that no longer exists.
        """
        create = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Servis Rem", "quantity": 1, "unit_price": 150000}]},
            format="json",
        )
        invoice_id = create.data["invoice"]["id"]
        self.client.patch(f"/api/invoices/{invoice_id}/status/", {"status": "ISSUED"}, format="json")

        total = create.data["invoice"]["total"]
        self.client.post(
            f"/api/invoices/{invoice_id}/payments/",
            {"amount": total, "method": "cash"},
            format="json",
        )
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


class TerbilangRupiahTests(SimpleTestCase):
    """
    Made's own handwritten meeting note, 4 Aug: "WO & Invoice:
    terbilang, diterima oleh." Chris's own confirmed scope, 5 Aug:
    Invoice only. Direct, real unit tests against the pure function —
    InvoicePdfTests above can't verify individual rendered text (no
    PDF-parsing library available), so this is the actual, precise
    coverage for the algorithm itself: a wrong spelled-out amount on
    a financial document is a real trust problem, not a cosmetic bug.
    SimpleTestCase, not APITestCase — no database touched at all.
    """

    def test_zero(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(0), "Nol Rupiah")

    def test_single_digit(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(1), "Satu Rupiah")

    def test_teens_use_belas_not_puluh(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(11), "Sebelas Rupiah")
        self.assertEqual(terbilang_rupiah(15), "Lima Belas Rupiah")

    def test_tens_with_a_remainder(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(21), "Dua Puluh Satu Rupiah")

    def test_exactly_one_hundred_uses_seratus_not_satu_ratus(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(100), "Seratus Rupiah")

    def test_exactly_one_thousand_uses_seribu_not_satu_ribu(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(1000), "Seribu Rupiah")

    def test_two_thousand_does_not_say_seribu_ribu(self):
        """The real reason seribu is a special case bounded at 2000,
        not just "n < 1000" — without it, 2000 would recurse into
        terbilang_words(2) + " ribu" on top of the 1000-1999 branch
        producing nonsense like "seribu ribu" for anything doubled."""
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(2000), "Dua Ribu Rupiah")

    def test_no_trailing_nol_when_a_remainder_is_genuinely_zero(self):
        """The actual bug the recursive algorithm has to avoid — a
        naive implementation emits a trailing 'nol' whenever a
        remainder is exactly zero (e.g. "tujuh ratus empat puluh ribu
        nol" for 740.000), which is wrong and would look broken on a
        real invoice."""
        from .pdf import terbilang_rupiah
        result = terbilang_rupiah(740000)
        self.assertEqual(result, "Tujuh Ratus Empat Puluh Ribu Rupiah")
        self.assertNotIn("Nol", result)

    def test_real_value_from_this_apps_own_example(self):
        """The exact total shown on a real invoice screenshot during
        this feature's own planning — Rp 740.000."""
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(740000), "Tujuh Ratus Empat Puluh Ribu Rupiah")

    def test_millions(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(1500000), "Satu Juta Lima Ratus Ribu Rupiah")

    def test_accepts_a_decimal_same_as_every_other_money_field_in_this_app(self):
        from .pdf import terbilang_rupiah
        self.assertEqual(terbilang_rupiah(Decimal("240000.00")), "Dua Ratus Empat Puluh Ribu Rupiah")


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
        """
        Made's own "no orphan completions" rule, 4 Aug, means
        WorkOrder.close() itself now ALSO rejects assigned_to=None —
        the normal path (WorkOrder -> close() -> ServiceRecord) can
        no longer produce a mechanic-less ServiceRecord at all, which
        is exactly the point (see the new, dedicated coverage for
        that rule in apps.workorders.tests.WorkOrderNoMechanicHardBlockTests).

        This helper now constructs the scenario directly via the ORM
        instead, bypassing close() entirely — still a real, defensible
        case (a ServiceRecord linked to a WorkOrder some other way,
        never through close() itself) and still the right place to
        prove Invoice.save()'s OWN, independent check actually holds,
        not merely that WorkOrder.close() happens to catch it first.
        """
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-31", odometer_km=5000,
            issue_description="Dibuat langsung, tanpa mekanik",
        )
        work_order.service_record = record
        work_order.save(update_fields=["service_record"])
        return record

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
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
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
