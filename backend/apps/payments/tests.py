# =============================================================================
# === backend/apps/payments/tests.py ===
# =============================================================================
"""
Fixture setUp() deliberately mirrors apps.invoicing.tests.
InvoicingAPITestBase almost exactly — same real WorkOrder -> close()
-> ServiceRecord -> Invoice chain, since a Payment can't exist
without a real Invoice, which can't exist without a real
ServiceRecord with a mechanic assigned. Not copy-pasted out of
laziness — this is genuinely the only way any of these objects come
into existence in production, so it's the only honest way to test
against them.
"""
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderJobLine
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Payment


class PaymentsAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.payments@test.id", password="pass12345!",
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
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Alex")

        work_order = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic,
        )
        work_order.status = "IN_PROGRESS"
        work_order.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order,
            description="(qc placeholder)", completed_at=timezone.now(),
        )
        work_order.status = "QC"
        work_order.save(update_fields=["status"])
        self.service_record = work_order.close(closed_by=self.owner)

        self.client.force_authenticate(user=self.owner)

        # An ISSUED invoice, total exactly Rp 250,000 — the one real
        # precondition Payment.record() requires before it will
        # accept anything (see apps.payments.models.Payment.record).
        create = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Servis", "quantity": 1, "unit_price": 250000}]},
            format="json",
        )
        self.invoice_id = create.data["invoice"]["id"]
        self.client.patch(
            f"/api/invoices/{self.invoice_id}/status/", {"status": "ISSUED"}, format="json",
        )

    def _pay(self, amount, **extra):
        body = {"amount": str(amount), "method": "cash", **extra}
        return self.client.post(f"/api/invoices/{self.invoice_id}/payments/", body, format="json")


class PaymentRecordingTests(PaymentsAPITestBase):

    def test_full_payment_marks_invoice_paid(self):
        resp = self._pay(250000)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "PAID")
        self.assertEqual(invoice.balance_due, Decimal("0.00"))

    def test_partial_payment_keeps_invoice_issued(self):
        resp = self._pay(100000)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "ISSUED")
        self.assertEqual(invoice.balance_due, Decimal("150000.00"))

    def test_two_partial_payments_together_complete_the_balance(self):
        """
        The exact real-world case this app exists for — a deposit at
        intake, a balance payment at pickup — two genuinely separate
        Payment rows against one Invoice, not one field overwritten
        twice.
        """
        first = self._pay(100000)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "ISSUED")

        second = self._pay(150000)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "PAID")
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 2)

    def test_overpayment_rejected(self):
        resp = self._pay(300000)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "ISSUED")
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())

    def test_zero_amount_rejected(self):
        resp = self._pay(0)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_amount_rejected(self):
        resp = self._pay(-50000)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pay_a_draft_invoice(self):
        create = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {}, format="json",
        )
        # This service_record already has an invoice from setUp() —
        # expect a 409 here confirming that, then build a genuinely
        # separate DRAFT invoice via a fresh visit instead.
        self.assertEqual(create.status_code, status.HTTP_409_CONFLICT)

        vehicle2 = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 3001 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Honda Brio",
        )
        wo2 = WorkOrder.objects.create(organization=self.org, vehicle=vehicle2, assigned_to=self.mechanic)
        wo2.status = "IN_PROGRESS"
        wo2.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=wo2, description="(qc placeholder)", completed_at=timezone.now(),
        )
        wo2.status = "QC"
        wo2.save(update_fields=["status"])
        record2 = wo2.close(closed_by=self.owner)
        create2 = self.client.post(f"/api/service-records/{record2.id}/invoice/", {}, format="json")
        draft_invoice_id = create2.data["invoice"]["id"]

        resp = self.client.post(
            f"/api/invoices/{draft_invoice_id}/payments/",
            {"amount": "1000", "method": "cash"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pay_an_already_paid_invoice(self):
        first = self._pay(250000)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._pay(1)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_pay_a_cancelled_invoice(self):
        self.client.patch(f"/api/invoices/{self.invoice_id}/status/", {"status": "CANCELLED"}, format="json")
        resp = self._pay(100000)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_payment_history_lists_all_payments_for_invoice(self):
        self._pay(100000)
        self._pay(150000)
        resp = self.client.get(f"/api/invoices/{self.invoice_id}/payments/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["payments"]), 2)

    def test_manual_status_paid_still_rejected_even_with_real_payment_endpoint_present(self):
        """
        The exact regression this whole app exists to prevent —
        proven again here, alongside the new endpoint, not just in
        apps.invoicing.tests. Both must hold together.
        """
        resp = self.client.patch(
            f"/api/invoices/{self.invoice_id}/status/", {"status": "PAID"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class PaymentTenantIsolationTests(PaymentsAPITestBase):

    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Bengkel Lain Payments")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherpayments@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_pay_org_a_invoice(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self._pay(100000)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_b_cannot_view_org_a_payment_history(self):
        self._pay(100000)
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/invoices/{self.invoice_id}/payments/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
