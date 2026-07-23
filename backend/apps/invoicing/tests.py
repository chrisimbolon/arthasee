# =============================================================================
# === backend/apps/invoicing/tests.py ===
# =============================================================================
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.inventory.models import Part, PartUsage, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
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
        self.service_record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle,
            service_date="2026-07-23", odometer_km=15003,
            issue_description="Rem terasa rendah",
        )
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
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=vehicle,
            service_date="2026-07-23", odometer_km=1000,
            issue_description="x",
        )
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
        other_record = ServiceRecord.objects.create(
            organization=other_org, vehicle=other_vehicle,
            service_date="2026-07-23", odometer_km=1000,
            issue_description="x",
        )
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
