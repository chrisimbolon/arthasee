# =============================================================================
# === backend/apps/purchasing/tests.py ===
# =============================================================================
"""
Sprint 3 — model-layer tests (Stage 1) plus real event/posting proof
(Stage 2). No HTTP endpoints exist yet — that's a later stage.
"""
from decimal import Decimal

from apps.accounting.models import Account
from apps.authentication.models import CustomUser
from apps.inventory.models import Part, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.payments.models import SupplierPayment
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (GoodsReceivedNote, PurchaseReturn, Supplier,
                     SupplierInvoice)


class PurchasingModelTestBase(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        # Required now that GoodsReceivedNote.receive() / SupplierInvoice.
        # record() actually publish real domain events — see
        # apps.payments.tests.PaymentsAPITestBase's own setUp for the
        # exact same reasoning, first surfaced there.
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.owner = CustomUser.objects.create_user(
            email="owner.purchasing@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        self.supplier = Supplier.objects.create(organization=self.org, name="PT Sparepart Jaya")
        self.part_a = Part.objects.create(
            organization=self.org, name="Oli Mesin", unit="liter",
            unit_price=Decimal("75000.00"), current_stock=Decimal("0"),
        )
        self.part_b = Part.objects.create(
            organization=self.org, name="Filter Oli", unit="pcs",
            unit_price=Decimal("60000.00"), current_stock=Decimal("5.00"),
        )


class GoodsReceivedNoteTests(PurchasingModelTestBase):

    def test_receive_creates_grn_with_sequential_number(self):
        grn = GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
            received_by=self.owner,
        )
        self.assertEqual(grn.number, "GRN/00001")
        self.assertEqual(grn.sequence_number, 1)

    def test_receive_increments_part_stock_via_real_stock_adjustment(self):
        self.assertEqual(self.part_a.current_stock, Decimal("0"))

        GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )

        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("10.00"))

        adjustment = StockAdjustment.objects.get(part=self.part_a)
        self.assertEqual(adjustment.reason, "restock")
        self.assertEqual(adjustment.quantity_change, Decimal("10.00"))

    def test_receive_with_multiple_lines_updates_each_part_independently(self):
        GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[
                {"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")},
                {"part": self.part_b, "quantity": Decimal("4.00"), "unit_cost": Decimal("40000.00")},
            ],
        )
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("10.00"))
        self.assertEqual(self.part_b.current_stock, Decimal("9.00"))  # 5 existing + 4 received

    def test_total_cost_aggregates_correctly_across_lines(self):
        grn = GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[
                {"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")},
                {"part": self.part_b, "quantity": Decimal("4.00"), "unit_cost": Decimal("40000.00")},
            ],
        )
        self.assertEqual(grn.total_cost, Decimal("610000.00"))

    def test_unit_cost_is_independent_of_part_unit_price(self):
        grn = GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("50000.00")}],
        )
        self.part_a.refresh_from_db()
        self.assertEqual(grn.line_items.first().unit_cost, Decimal("50000.00"))
        self.assertEqual(self.part_a.unit_price, Decimal("75000.00"))  # untouched

    def test_receive_requires_at_least_one_line(self):
        with self.assertRaises(ValueError):
            GoodsReceivedNote.receive(organization=self.org, supplier=self.supplier, lines=[])

    def test_grn_numbers_are_scoped_per_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Purchasing")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, supplier=other_supplier,
            lines=[{"part": other_part, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        self.assertEqual(other_grn.number, "GRN/00001")  # not 00002 — separate sequence


class SupplierInvoiceTests(PurchasingModelTestBase):

    def _receive(self, cost=Decimal("450000.00")):
        return GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00")}],
        )

    def test_invoice_can_link_multiple_grns(self):
        grn1 = self._receive(Decimal("450000.00"))
        grn2 = self._receive(Decimal("200000.00"))

        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("650000.00"), invoice_date="2026-08-09",
            goods_received_notes=[grn1, grn2],
        )

        grn1.refresh_from_db()
        grn2.refresh_from_db()
        self.assertEqual(grn1.supplier_invoice_id, invoice.id)
        self.assertEqual(grn2.supplier_invoice_id, invoice.id)
        self.assertEqual(invoice.goods_received_notes.count(), 2)

    def test_amount_is_not_derived_from_grn_totals(self):
        grn = self._receive(Decimal("450000.00"))
        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("475000.00"),
            invoice_date="2026-08-09", goods_received_notes=[grn],
        )
        self.assertEqual(invoice.amount, Decimal("475000.00"))

    def test_cannot_link_a_grn_already_linked_to_another_invoice(self):
        grn = self._receive()
        SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("450000.00"), invoice_date="2026-08-09",
            goods_received_notes=[grn],
        )
        with self.assertRaises(ValueError):
            SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("450000.00"), invoice_date="2026-08-10",
                goods_received_notes=[grn],
            )

    def test_zero_or_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("0"), invoice_date="2026-08-09",
            )

    def test_invoice_numbers_are_scoped_per_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Purchasing Invoice")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("100000.00"), invoice_date="2026-08-09",
        )
        other_invoice = SupplierInvoice.record(
            organization=other_org, supplier=other_supplier,
            amount=Decimal("100000.00"), invoice_date="2026-08-09",
        )
        self.assertEqual(other_invoice.number, "SINV/00001")


class PurchaseReturnTests(PurchasingModelTestBase):

    def _receive(self, quantity=Decimal("10.00"), unit_cost=Decimal("45000.00")):
        return GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": quantity, "unit_cost": unit_cost}],
        )

    def test_create_return_creates_sequential_number(self):
        grn = self._receive()
        ret = PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn.line_items.first(), "quantity": Decimal("2.00")}],
            reason="Barang rusak",
        )
        self.assertEqual(ret.number, "RTR/00001")

    def test_return_decreases_part_stock_via_real_stock_adjustment(self):
        grn = self._receive(quantity=Decimal("10.00"))
        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("10.00"))

        PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn.line_items.first(), "quantity": Decimal("3.00")}],
            reason="Salah kirim",
        )
        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("7.00"))

        adjustment = StockAdjustment.objects.get(part=self.part_a, reason="purchase_return")
        self.assertEqual(adjustment.quantity_change, Decimal("-3.00"))

    def test_return_blocked_if_grn_already_has_supplier_invoice(self):
        """
        The real Case-A guard — the whole reason v1 is scoped the way
        it is. Once an invoice exists, Accrued Inventory is already
        cleared and this reversal would be silently wrong.
        """
        grn = self._receive()
        SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("450000.00"), invoice_date="2026-08-09",
            goods_received_notes=[grn],
        )
        with self.assertRaises(ValueError):
            PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn,
                lines=[{"grn_line_item": grn.line_items.first(), "quantity": Decimal("1.00")}],
                reason="Terlambat",
            )

    def test_partial_returns_accumulate_and_cap_at_original_quantity(self):
        """
        Real proof of the cumulative cap — verified by hand before
        being written into this codebase. First return of 6 succeeds;
        a second return of 5 more (totalling 11 against 10 received)
        is blocked; a second return of 4 more (totalling exactly 10)
        succeeds.
        """
        grn = self._receive(quantity=Decimal("10.00"))
        grn_line = grn.line_items.first()

        PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn_line, "quantity": Decimal("6.00")}],
            reason="Retur pertama",
        )

        with self.assertRaises(ValueError):
            PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn,
                lines=[{"grn_line_item": grn_line, "quantity": Decimal("5.00")}],
                reason="Melebihi kuota",
            )

        PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn_line, "quantity": Decimal("4.00")}],
            reason="Retur kedua, pas batas",
        )
        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("0.00"))  # 10 received - 6 - 4

    def test_unit_cost_snapshot_from_original_grn_line_not_live_part_price(self):
        grn = self._receive(unit_cost=Decimal("45000.00"))
        ret = PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn.line_items.first(), "quantity": Decimal("2.00")}],
            reason="Test",
        )
        self.part_a.unit_price = Decimal("99999.00")
        self.part_a.save(update_fields=["unit_price"])

        line = ret.line_items.first()
        self.assertEqual(line.unit_cost, Decimal("45000.00"))  # untouched by the price change
        self.assertEqual(line.subtotal, Decimal("90000.00"))   # 2 * 45000

    def test_return_requires_at_least_one_line(self):
        grn = self._receive()
        with self.assertRaises(ValueError):
            PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn, lines=[], reason="Kosong",
            )

    def test_cannot_return_a_line_item_from_a_different_grn(self):
        grn1 = self._receive()
        grn2 = self._receive()
        with self.assertRaises(ValueError):
            PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn1,
                lines=[{"grn_line_item": grn2.line_items.first(), "quantity": Decimal("1.00")}],
                reason="Salah GRN",
            )

class SupplierPaymentTests(PurchasingModelTestBase):

    def _unpaid_invoice(self, amount=Decimal("450000.00")):
        return SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=amount, invoice_date="2026-08-09",
        )

    def test_payment_pays_the_full_invoice_amount(self):
        invoice = self._unpaid_invoice(Decimal("450000.00"))
        payment = SupplierPayment.record(supplier_invoice=invoice, method="bank_transfer")
        self.assertEqual(payment.amount, Decimal("450000.00"))

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "PAID")

    def test_cannot_pay_an_already_paid_invoice(self):
        invoice = self._unpaid_invoice()
        SupplierPayment.record(supplier_invoice=invoice, method="bank_transfer")
        with self.assertRaises(ValueError):
            SupplierPayment.record(supplier_invoice=invoice, method="bank_transfer")

    def test_payment_method_defaults_to_bank_transfer(self):
        invoice = self._unpaid_invoice()
        payment = SupplierPayment.record(supplier_invoice=invoice)
        self.assertEqual(payment.method, "bank_transfer")


class GoodsReceivedEventTests(PurchasingModelTestBase):
    """
    Sprint 3, Stage 2 — proves receiving goods actually posts the
    real GR/IR clearing entry, not just that the model layer runs
    without error.
    """

    def test_receive_posts_inventory_and_accrued_inventory(self):
        with self.captureOnCommitCallbacks(execute=True):
            GoodsReceivedNote.receive(
                organization=self.org, supplier=self.supplier,
                lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
            )

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        # 10 * 45000 = 450000 — verified by hand before this
        # assertion was written.
        self.assertEqual(inventory.balance(), Decimal("450000.00"))
        self.assertEqual(accrued.balance(), Decimal("450000.00"))


class SupplierInvoiceReceivedEventTests(PurchasingModelTestBase):
    """
    Sprint 3, Stage 2 — proves recording a supplier invoice clears
    Accrued Inventory into real Accounts Payable, AND proves the
    "no 3-way matching" design decision holds all the way to the
    ledger, not just in the model layer.
    """

    def _received_grn(self, cost=Decimal("450000.00")):
        with self.captureOnCommitCallbacks(execute=True):
            return GoodsReceivedNote.receive(
                organization=self.org, supplier=self.supplier,
                lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00")}],
            )

    def test_invoice_clears_accrued_inventory_into_accounts_payable(self):
        grn = self._received_grn()

        with self.captureOnCommitCallbacks(execute=True):
            SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("450000.00"), invoice_date="2026-08-09",
                goods_received_notes=[grn],
            )

        accrued = Account.objects.get(organization=self.org, code="2010")
        ap      = Account.objects.get(organization=self.org, code="2001")
        # Net effect across both events: accrued back to zero, AP now
        # holds the real payable.
        self.assertEqual(accrued.balance(), Decimal("0.00"))
        self.assertEqual(ap.balance(), Decimal("450000.00"))

    def test_invoice_amount_mismatch_with_grn_still_posts_the_stated_amount(self):
        """
        The real proof the design decision holds — a supplier's
        stated total that differs from what was accrued posts exactly
        as stated, leaving a real, visible variance on Accrued
        Inventory rather than being silently force-corrected to match
        the GRN.
        """
        grn = self._received_grn(Decimal("450000.00"))

        with self.captureOnCommitCallbacks(execute=True):
            SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("475000.00"),  # deliberately different from the GRN's own 450000
                invoice_date="2026-08-09", goods_received_notes=[grn],
            )

        accrued = Account.objects.get(organization=self.org, code="2010")
        ap      = Account.objects.get(organization=self.org, code="2001")
        # +450000 (GRN credit) - 475000 (invoice debit) = -25000 — a
        # real, visible variance, verified by hand before this
        # assertion was written, not hidden or auto-corrected.
        self.assertEqual(accrued.balance(), Decimal("-25000.00"))
        self.assertEqual(ap.balance(), Decimal("475000.00"))

class PurchasingAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.owner = CustomUser.objects.create_user(
            email="owner.purchasing.api@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.supplier = Supplier.objects.create(organization=self.org, name="PT Sparepart Jaya")
        self.part = Part.objects.create(
            organization=self.org, name="Oli Mesin", unit="liter",
            unit_price=Decimal("75000.00"), current_stock=Decimal("0"),
        )
        self.client.force_authenticate(user=self.owner)


class SupplierAPITests(PurchasingAPITestBase):

    def test_create_supplier(self):
        resp = self.client.post("/api/suppliers/", {"name": "Supplier Baru"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["supplier"]["name"], "Supplier Baru")

    def test_list_suppliers_scoped_to_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Purchasing API")
        Supplier.objects.create(organization=other_org, name="Supplier Org Lain")

        resp = self.client.get("/api/suppliers/")
        names = [s["name"] for s in resp.data["suppliers"]]
        self.assertIn("PT Sparepart Jaya", names)
        self.assertNotIn("Supplier Org Lain", names)


class GoodsReceivedNoteAPITests(PurchasingAPITestBase):

    def test_create_grn_via_api_posts_real_journal_entry(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post("/api/goods-received-notes/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"))

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        self.assertEqual(inventory.balance(), Decimal("450000.00"))
        self.assertEqual(accrued.balance(), Decimal("450000.00"))

    def test_create_grn_rejects_cross_tenant_part(self):
        """
        The real proof the UUIDField-not-PrimaryKeyRelatedField
        design decision actually holds — referencing another shop's
        Part must be structurally impossible, not just discouraged.
        This is the single most important test in this whole batch.
        """
        other_org = Organization.objects.create(name="Bengkel Lain GRN Part")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )

        resp = self.client.post("/api/goods-received-notes/", {
            "supplier": str(self.supplier.id),
            "lines": [{"part": str(other_part.id), "quantity": "1.00", "unit_cost": "1000.00"}],
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(GoodsReceivedNote.objects.exists())  # nothing partial got created

    def test_create_grn_rejects_cross_tenant_supplier(self):
        other_org = Organization.objects.create(name="Bengkel Lain GRN Supplier")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Org Lain")

        resp = self.client.post("/api/goods-received-notes/", {
            "supplier": str(other_supplier.id),
            "lines": [{"part": str(self.part.id), "quantity": "1.00", "unit_cost": "1000.00"}],
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_b_cannot_see_org_a_goods_received_notes(self):
        GoodsReceivedNote.receive(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_org = Organization.objects.create(name="Bengkel Lain GRN List")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherorg.grn@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=other_org, user=other_owner, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=other_owner)

        resp = self.client.get("/api/goods-received-notes/")
        self.assertEqual(resp.data["goods_received_notes"], [])


class SupplierInvoiceAPITests(PurchasingAPITestBase):

    def test_full_round_trip_receive_invoice_and_pay(self):
        """
        The real end-to-end proof — receive goods, bill it, pay it,
        all through the actual HTTP endpoints, confirming the ledger
        is correct at every step, not just that each call returns
        the right status code.
        """
        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        grn_id = grn_resp.data["goods_received_note"]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            invoice_resp = self.client.post("/api/supplier-invoices/", {
                "supplier": str(self.supplier.id),
                "amount": "450000.00",
                "invoice_date": "2026-08-09",
                "goods_received_note_ids": [grn_id],
            }, format="json")
        self.assertEqual(invoice_resp.status_code, status.HTTP_201_CREATED)
        supplier_invoice_id = invoice_resp.data["supplier_invoice"]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            pay_resp = self.client.post(
                f"/api/supplier-invoices/{supplier_invoice_id}/pay/",
                {"method": "bank_transfer"}, format="json",
            )
        self.assertEqual(pay_resp.status_code, status.HTTP_201_CREATED)

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        ap        = Account.objects.get(organization=self.org, code="2001")
        bank      = Account.objects.get(organization=self.org, code="1101")

        self.assertEqual(inventory.balance(), Decimal("450000.00"))  # real stock received
        self.assertEqual(accrued.balance(), Decimal("0.00"))          # cleared by the invoice
        self.assertEqual(ap.balance(), Decimal("0.00"))               # cleared by the payment
        self.assertEqual(bank.balance(), Decimal("-450000.00"))       # real cash outflow

    def test_invoice_endpoint_rejects_cross_tenant_grn(self):
        other_org = Organization.objects.create(name="Bengkel Lain SINV GRN")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Org Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, supplier=other_supplier,
            lines=[{"part": other_part, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )

        resp = self.client.post("/api/supplier-invoices/", {
            "supplier": str(self.supplier.id),
            "amount": "1000.00",
            "invoice_date": "2026-08-09",
            "goods_received_note_ids": [str(other_grn.id)],
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(SupplierInvoice.objects.exists())

class PurchaseReturnAPITests(PurchasingAPITestBase):

    def test_create_purchase_return_via_api_posts_real_journal_entry(self):
        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        grn_data = grn_resp.data["goods_received_note"]
        grn_line_id = grn_data["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            return_resp = self.client.post("/api/purchase-returns/", {
                "goods_received_note": grn_data["id"],
                "reason": "Barang rusak saat diterima",
                "lines": [{"grn_line_item": grn_line_id, "quantity": "3.00"}],
            }, format="json")
        self.assertEqual(return_resp.status_code, status.HTTP_201_CREATED)

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("7.00"))  # 10 received - 3 returned

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        # 450000 received - 135000 returned (3 * 45000) = 315000
        self.assertEqual(inventory.balance(), Decimal("315000.00"))
        self.assertEqual(accrued.balance(), Decimal("315000.00"))

    def test_return_rejects_grn_already_invoiced(self):
        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        grn_data = grn_resp.data["goods_received_note"]

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/supplier-invoices/", {
                "supplier": str(self.supplier.id),
                "amount": "450000.00",
                "invoice_date": "2026-08-09",
                "goods_received_note_ids": [grn_data["id"]],
            }, format="json")

        resp = self.client.post("/api/purchase-returns/", {
            "goods_received_note": grn_data["id"],
            "reason": "Terlambat",
            "lines": [{"grn_line_item": grn_data["line_items"][0]["id"], "quantity": "1.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_return_rejects_cross_tenant_grn(self):
        other_org = Organization.objects.create(name="Bengkel Lain Return")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, supplier=other_supplier,
            lines=[{"part": other_part, "quantity": Decimal("5.00"), "unit_cost": Decimal("1000.00")}],
        )

        resp = self.client.post("/api/purchase-returns/", {
            "goods_received_note": str(other_grn.id),
            "reason": "Tidak sah",
            "lines": [{"grn_line_item": str(other_grn.line_items.first().id), "quantity": "1.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(PurchaseReturn.objects.exists())

    def test_org_b_cannot_see_org_a_purchase_returns(self):
        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "5.00", "unit_cost": "1000.00"}],
            }, format="json")
        grn_data = grn_resp.data["goods_received_note"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/purchase-returns/", {
                "goods_received_note": grn_data["id"],
                "reason": "Test",
                "lines": [{"grn_line_item": grn_data["line_items"][0]["id"], "quantity": "1.00"}],
            }, format="json")

        other_org = Organization.objects.create(name="Bengkel Lain Return List")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherorg.return@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=other_org, user=other_owner, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=other_owner)

        resp = self.client.get("/api/purchase-returns/")
        self.assertEqual(resp.data["purchase_returns"], [])