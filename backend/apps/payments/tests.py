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
import uuid
from datetime import datetime as dt
from datetime import timedelta
from decimal import Decimal

from apps.accounting import cancellations
from apps.accounting.models import Account, JournalEntry
from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.invoicing.events import InvoiceRefunded
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization, OrganizationMembership
from apps.payments.models import OperatingExpense, SupplierPayment
from apps.purchasing.models import Supplier, SupplierInvoice
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderJobLine
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Payment


class PaymentsAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
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
        # Wrapped in captureOnCommitCallbacks — this fixture predates
        # InvoiceIssued (written before that event existed), so this
        # PATCH was never deferring anything at the time. Now it
        # triggers InvoiceIssued, whose JournalEntry several tests
        # depend on existing (InvoiceRefundTests especially — its
        # whole point is finding and reversing this exact posting).
        # Without this wrapper, the on_commit callback never fires
        # inside a test, and the original posting silently never
        # happens — invisible until a test actually checked for it.
        with self.captureOnCommitCallbacks(execute=True):
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

class PaymentReceivedEventTests(PaymentsAPITestBase):

    def test_full_payment_publishes_payment_received(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._pay(250000, method="cash")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        row = Outbox.objects.get(event_type="PaymentReceived", payload__invoice_id=self.invoice_id)
        self.assertEqual(row.organization_id, self.org.id)
        # Payment.amount is a raw stored DecimalField(decimal_places=2),
        # not a multiplication result — 2 decimal places, not 4. See
        # apps.payments.events.PaymentReceived's own docstring for why
        # this differs from the other three Sprint 2 events, verified
        # by hand before this assertion was written.
        self.assertEqual(row.payload["amount"], "250000.00")
        self.assertEqual(row.payload["method"], "cash")
        self.assertEqual(row.status, Outbox.Status.PROCESSED)

    def test_partial_payment_still_publishes_payment_received(self):
        """
        Chris's own explicit call — a partial payment is just as real
        a cash movement as a full one, and must publish the same way,
        even though the invoice itself stays ISSUED afterward.
        """
        with self.captureOnCommitCallbacks(execute=True):
            self._pay(100000, method="bank_transfer")

        row = Outbox.objects.get(event_type="PaymentReceived", payload__invoice_id=self.invoice_id)
        self.assertEqual(row.payload["amount"], "100000.00")
        self.assertEqual(row.payload["method"], "bank_transfer")

    def test_two_partial_payments_publish_two_separate_events(self):
        self._pay(100000)
        self._pay(150000)
        rows = Outbox.objects.filter(event_type="PaymentReceived", payload__invoice_id=self.invoice_id)
        self.assertEqual(rows.count(), 2)
        amounts = sorted(row.payload["amount"] for row in rows)
        self.assertEqual(amounts, ["100000.00", "150000.00"])

    def test_payment_id_in_payload_matches_the_real_payment_row(self):
        resp = self._pay(250000)
        payment_id = resp.data["payment"]["id"]
        row = Outbox.objects.get(event_type="PaymentReceived", payload__invoice_id=self.invoice_id)
        self.assertEqual(row.payload["payment_id"], payment_id)

    def test_rejected_overpayment_publishes_nothing(self):
        """
        The failed-validation path in Payment.record() raises before
        ever reaching the publish() call — confirms that a rejected
        attempt leaves no Outbox trace, same "fail before writing
        anything" discipline as JournalEntry.post().
        """
        resp = self._pay(300000)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Outbox.objects.filter(event_type="PaymentReceived").count(), 0)

class InvoiceRefundTests(PaymentsAPITestBase):
    """
    Task 2.3, Half B — proves refunding a fully-paid invoice reverses
    the exact revenue posting WITHOUT touching AR (which is already
    correctly at zero from the payment that got it there), and
    credits the right cash/bank account based on the refund's own
    method — independent of whatever method the original payment used.
    """

    def _pay_in_full(self, method="cash"):
        with self.captureOnCommitCallbacks(execute=True):
            self._pay(250000, method=method)

    def test_refunding_paid_invoice_reverses_revenue_not_ar(self):
        self._pay_in_full(method="cash")
        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "PAID")

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                f"/api/invoices/{self.invoice_id}/refund/", {"method": "cash"}, format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "CANCELLED")

        service_rev = Account.objects.get(organization=self.org, code="4001")
        cash        = Account.objects.get(organization=self.org, code="1001")
        ar          = Account.objects.get(organization=self.org, code="1201")

        # Revenue reversed to net zero.
        self.assertEqual(service_rev.balance(), Decimal("0.00"))
        # AR untouched by the refund — already correctly zero from
        # PaymentReceived clearing it, not re-credited by this reversal.
        self.assertEqual(ar.balance(), Decimal("0.00"))
        # Cash: +250000 from the payment, -250000 from the refund.
        self.assertEqual(cash.balance(), Decimal("0.00"))

    def test_refund_method_is_independent_of_payment_method(self):
        """
        The original payment came in as cash; the refund goes out via
        bank transfer — a completely normal real-world case. Cash
        should show ONLY the original inflow (untouched by this
        refund); Bank should show ONLY the refund outflow.
        """
        self._pay_in_full(method="cash")

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/api/invoices/{self.invoice_id}/refund/", {"method": "bank_transfer"}, format="json",
            )

        cash = Account.objects.get(organization=self.org, code="1001")
        bank = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(cash.balance(), Decimal("250000.00"))    # payment only, untouched by refund
        self.assertEqual(bank.balance(), Decimal("-250000.00"))   # refund only

    def test_cannot_refund_an_unpaid_invoice(self):
        # self.invoice_id is ISSUED, unpaid, straight from
        # PaymentsAPITestBase's own setUp — never paid in this test.
        resp = self.client.post(
            f"/api/invoices/{self.invoice_id}/refund/", {"method": "cash"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refunding_twice_is_blocked_by_status_guard(self):
        self._pay_in_full(method="cash")
        with self.captureOnCommitCallbacks(execute=True):
            first = self.client.post(
                f"/api/invoices/{self.invoice_id}/refund/", {"method": "cash"}, format="json",
            )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        # Invoice is now CANCELLED, not PAID — Refund.record()'s own
        # status guard rejects it, same as any already-refunded invoice.
        second = self.client.post(
            f"/api/invoices/{self.invoice_id}/refund/", {"method": "cash"}, format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_calling_reverse_for_refund_event_twice_does_not_double_reverse(self):
        """
        Idempotency guard, proven directly against cancellations.
        reverse_for_refund_event() itself — same reasoning as every
        other idempotency test this sprint: going through
        default_bus.publish() twice for the same event_id would hit
        Outbox's own unique constraint first, so the guard is tested
        by calling the function directly instead.
        """
        self._pay_in_full(method="cash")
        invoice = Invoice.objects.get(id=self.invoice_id)

        refund_event = InvoiceRefunded(
            organization_id=self.org.id, invoice_id=invoice.id,
            refund_id=uuid.uuid4(), issued_event_id=invoice.issued_event_id,
            amount=Decimal("250000.00"), method="cash",
        )
        cancellations.reverse_for_refund_event(refund_event)
        cancellations.reverse_for_refund_event(refund_event)  # same event, called again directly

        self.assertEqual(
            JournalEntry.objects.filter(reference_event_id=refund_event.event_id).count(), 1,
        )

    def test_status_patch_to_cancelled_on_paid_invoice_points_at_refund_endpoint(self):
        """
        The old guard on InvoiceStatusUpdateView still blocks the raw
        status PATCH for a paid invoice — confirms the message was
        actually updated to reference the new endpoint, not just that
        the block still exists (already covered elsewhere).
        """
        self._pay_in_full(method="cash")
        resp = self.client.patch(
            f"/api/invoices/{self.invoice_id}/status/", {"status": "CANCELLED"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("refund", resp.data["message"].lower())

    def test_missing_cash_account_marks_outbox_failed_not_silent(self):
        """
        Closes the gap flagged after Half B shipped — Account.resolve()
        is called from TWO places now: journal_generator.py (already
        proven to fail loudly via
        apps.accounting.tests.PostingEngineIntegrationTests) and
        cancellations.py's own refund reversal, for the cash/bank
        credit line specifically. Proves the second call site
        degrades the exact same correct way: Outbox marked FAILED
        with the error captured, no partial JournalEntry ever created
        — not a silent, incomplete reversal.

        Pays via bank_transfer specifically, not cash — Cash(1001)
        then has zero real JournalLine history for this org, so it
        can actually be deleted for the test (Account has
        on_delete=PROTECT; deleting an account with real postings
        against it would raise ProtectedError, which is correct
        behavior, not something to route around). The refund is then
        requested via method="cash" — deliberately mismatched from
        the payment's own method — forcing the reversal to need
        exactly the account that's now missing.

        The refund itself still succeeds (201, invoice really becomes
        CANCELLED) even though the reversal posting fails — the
        handler runs AFTER Refund.record()'s own transaction has
        already committed (deferred via transaction.on_commit()), so
        its failure can't roll back the business action that
        triggered it. Same deliberate guarantee this whole event
        system has had since Sprint 1, not a new inconsistency — the
        accounting reversal failing is a real, visible problem for
        someone to go fix (a FAILED Outbox row, an unreversed
        ledger), not a reason to have blocked the refund itself.
        """
        self._pay_in_full(method="bank_transfer")

        Account.objects.get(organization=self.org, code="1001").delete()

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                f"/api/invoices/{self.invoice_id}/refund/", {"method": "cash"}, format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        invoice = Invoice.objects.get(id=self.invoice_id)
        self.assertEqual(invoice.status, "CANCELLED")  # the refund itself still went through

        row = Outbox.objects.get(event_type="InvoiceRefunded", payload__invoice_id=str(invoice.id))
        self.assertEqual(row.status, Outbox.Status.FAILED)
        self.assertIn("CancellationEventHandler", row.last_error)

        self.assertFalse(JournalEntry.objects.filter(event_type="InvoiceRefunded").exists())

class SupplierPaymentMadeEventTests(TestCase):
    """
    Sprint 3, Stage 2 — needs its own fixture, not
    PaymentsAPITestBase (that fixture is built around a customer
    Invoice, not a SupplierInvoice). Proves paying a supplier
    actually posts Dr AP / Cr Cash-or-Bank, clearing the payable for
    real.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.supplier = Supplier.objects.create(organization=self.org, name="PT Sparepart Jaya")
        with self.captureOnCommitCallbacks(execute=True):
            self.invoice = SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("450000.00"), invoice_date="2026-08-09",
            )

    def test_payment_clears_ap_and_credits_bank(self):
        with self.captureOnCommitCallbacks(execute=True):
            SupplierPayment.record(supplier_invoice=self.invoice, method="bank_transfer")

        ap   = Account.objects.get(organization=self.org, code="2001")
        bank = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(ap.balance(), Decimal("0.00"))          # payable cleared
        self.assertEqual(bank.balance(), Decimal("-450000.00"))  # real cash outflow

    def test_payment_via_cash_credits_cash_not_bank(self):
        with self.captureOnCommitCallbacks(execute=True):
            SupplierPayment.record(supplier_invoice=self.invoice, method="cash")

        cash = Account.objects.get(organization=self.org, code="1001")
        bank = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(cash.balance(), Decimal("-450000.00"))
        self.assertEqual(bank.balance(), Decimal("0.00"))


class OperatingExpenseTests(TestCase):
    """
    27-28 Aug 2026 — Made's own confirmed real request: a guided
    "Catat Beban Operasional" form. Own fixture, not
    PaymentsAPITestBase — OperatingExpense needs no Invoice/WorkOrder
    chain at all, just a seeded org and, for the mechanic-attribution
    tests, a real Mechanic.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Yoga")

    def test_record_creates_sequential_number(self):
        account = Account.objects.get(organization=self.org, code="6003")
        with self.captureOnCommitCallbacks(execute=True):
            expense = OperatingExpense.record(
                organization=self.org, account=account, amount=Decimal("300000.00"),
            )
        self.assertEqual(expense.number, "EXP/00001")
        self.assertEqual(expense.sequence_number, 1)

    def test_cash_expense_posts_dr_account_cr_cash(self):
        account = Account.objects.get(organization=self.org, code="6003")
        with self.captureOnCommitCallbacks(execute=True):
            OperatingExpense.record(
                organization=self.org, account=account, amount=Decimal("300000.00"), method="cash",
            )
        utilities = Account.objects.get(organization=self.org, code="6003")
        cash      = Account.objects.get(organization=self.org, code="1001")
        self.assertEqual(utilities.balance(), Decimal("300000.00"))
        self.assertEqual(cash.balance(), Decimal("-300000.00"))

    def test_bank_expense_posts_dr_account_cr_bank(self):
        account = Account.objects.get(organization=self.org, code="6001")
        with self.captureOnCommitCallbacks(execute=True):
            OperatingExpense.record(
                organization=self.org, account=account, amount=Decimal("6000000.00"), method="bank",
            )
        salary = Account.objects.get(organization=self.org, code="6001")
        bank   = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(salary.balance(), Decimal("6000000.00"))
        self.assertEqual(bank.balance(), Decimal("-6000000.00"))

    def test_posting_date_matches_paid_at_not_occurred_at(self):
        """
        Real regression test, 28 Aug 2026 — found live, via Chris's
        own manual testing, not caught by any test before this one:
        journal_generator.post_for_event() originally hardcoded
        event.occurred_at.date() (WHEN the event was published,
        practically always "now") instead of the real business date
        the user actually chose. paid_at set to yesterday specifically
        — clearly, unambiguously DIFFERENT from occurred_at (today,
        since this event is published live during this exact test) —
        so a real regression back to the old bug would make this
        assertion fail with today's date instead of yesterday's, not
        silently pass either way.
        """
        account = Account.objects.get(organization=self.org, code="6003")
        yesterday = timezone.now() - timedelta(days=1)

        with self.captureOnCommitCallbacks(execute=True):
            expense = OperatingExpense.record(
                organization=self.org, account=account, amount=Decimal("100000.00"),
                paid_at=yesterday,
            )
        
        entry = JournalEntry.objects.get(organization=self.org, event_type="OperatingExpenseRecorded")
        self.assertEqual(entry.posting_date, yesterday.date())

    def test_account_must_be_expense_type(self):
        cash_account = Account.objects.get(organization=self.org, code="1001")  # ASSET, not EXPENSE
        with self.assertRaises(ValueError):
            OperatingExpense.record(organization=self.org, account=cash_account, amount=Decimal("100000.00"))

    def test_6004_depreciation_account_rejected(self):
        """
        Real, deliberate exclusion — 6004 is reserved for the
        separate depreciation engine (non-cash, credits a contra-
        asset account, not Cash/Bank). Posting through this form
        would produce a real, wrong journal entry.
        """
        depreciation_account = Account.objects.get(organization=self.org, code="6004")
        with self.assertRaises(ValueError):
            OperatingExpense.record(
                organization=self.org, account=depreciation_account, amount=Decimal("50000.00"),
            )

    def test_mechanic_allowed_for_gaji_karyawan(self):
        salary_account = Account.objects.get(organization=self.org, code="6001")
        with self.captureOnCommitCallbacks(execute=True):
            expense = OperatingExpense.record(
                organization=self.org, account=salary_account, amount=Decimal("6000000.00"),
                mechanic=self.mechanic,
            )
        self.assertEqual(expense.mechanic_id, self.mechanic.id)

    def test_mechanic_rejected_for_non_salary_account(self):
        utilities_account = Account.objects.get(organization=self.org, code="6003")
        with self.assertRaises(ValueError):
            OperatingExpense.record(
                organization=self.org, account=utilities_account, amount=Decimal("300000.00"),
                mechanic=self.mechanic,
            )

    def test_zero_amount_rejected(self):
        account = Account.objects.get(organization=self.org, code="6003")
        with self.assertRaises(ValueError):
            OperatingExpense.record(organization=self.org, account=account, amount=Decimal("0"))

    def test_negative_amount_rejected(self):
        account = Account.objects.get(organization=self.org, code="6003")
        with self.assertRaises(ValueError):
            OperatingExpense.record(organization=self.org, account=account, amount=Decimal("-50000.00"))

    def test_blocked_when_target_period_is_closed(self):
        """
        Real, direct proof of the synchronous period-lock guard for
        THIS specific write path — never explicitly tested before,
        even though it's the exact mechanism that caught the real
        August-closed-period block live during manual testing.
        """
        from apps.accounting.models import AccountingPeriod
        period = AccountingPeriod.objects.get(organization=self.org, year=2026, month=1)
        period.close(closed_by=None)

        account = Account.objects.get(organization=self.org, code="6003")
        with self.assertRaises(ValueError):
            OperatingExpense.record(
                organization=self.org, account=account, amount=Decimal("100000.00"),
                paid_at=timezone.make_aware(dt(2026, 1, 15)),
            )


class OperatingExpenseAPITests(APITestCase):
    """Thin-view smoke test — the real logic is already fully proven
    at the model layer above; this confirms the endpoint itself wires
    everything together correctly end to end."""

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.owner = CustomUser.objects.create_user(
            email="owner.opex@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=self.owner)

    def test_create_operating_expense_via_api(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post("/api/operating-expenses/", {
                "account_code": "6003", "amount": "300000.00", "method": "cash",
            }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        utilities = Account.objects.get(organization=self.org, code="6003")
        self.assertEqual(utilities.balance(), Decimal("300000.00"))

    def test_6004_rejected_via_api(self):
        resp = self.client.post("/api/operating-expenses/", {
            "account_code": "6004", "amount": "50000.00", "method": "cash",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(OperatingExpense.objects.exists())

    def test_rejects_cross_tenant_mechanic(self):
        other_org = Organization.objects.create(name="Bengkel Lain OpEx")
        other_mechanic = Mechanic.objects.create(organization=other_org, name="Mekanik Lain")

        resp = self.client.post("/api/operating-expenses/", {
            "account_code": "6001", "amount": "6000000.00", "method": "cash",
            "mechanic": str(other_mechanic.id),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(OperatingExpense.objects.exists())