# =============================================================================
# === backend/apps/purchasing/tests.py ===
# =============================================================================
"""
Sprint 3, Stage 1 — model-layer tests only. No HTTP endpoints exist
yet (that's a later stage), and no domain events fire yet (Stage 2) —
these prove GoodsReceivedNote.receive() / SupplierInvoice.record() /
SupplierPayment.record() are correct in isolation, the same
"models first, confirm solid" discipline the Stage 1 delivery itself
was built around.
"""
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.inventory.models import Part, StockAdjustment
from apps.organizations.models import Organization
from apps.payments.models import SupplierPayment
from django.test import TestCase

from .models import GoodsReceivedNote, Supplier, SupplierInvoice


class PurchasingModelTestBase(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
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
        """
        The real point of Stage 1 — proves receiving goods reuses
        StockAdjustment(reason="restock"), not a fourth independent
        copy of stock math.
        """
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
        # 10*45000 + 4*40000 = 450000 + 160000 = 610000 — verified by
        # hand before this assertion was written.
        self.assertEqual(grn.total_cost, Decimal("610000.00"))

    def test_unit_cost_is_independent_of_part_unit_price(self):
        """
        The real gap this whole design was built to close —
        unit_cost (what was PAID) must never be confused with
        Part.unit_price (what's CHARGED to customers). Buying at a
        discount below the normal selling price must not silently
        alter what customers get charged.
        """
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
        """
        The real point of Half B's design decision — one supplier
        invoice consolidating several separate deliveries.
        """
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
        """
        Deliberate — proves the "no 3-way matching" design decision
        actually holds: a supplier's stated total can legitimately
        differ from what was accrued, and this doesn't get silently
        corrected or blocked.
        """
        grn = self._receive(Decimal("450000.00"))
        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("475000.00"),  # deliberately different from the GRN's own 450000
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
        """
        Deliberately different default from Payment/Refund's own
        "cash" default — a real business reflection: shops pay
        suppliers by bank transfer far more often than they receive
        cash from customers.
        """
        invoice = self._unpaid_invoice()
        payment = SupplierPayment.record(supplier_invoice=invoice)
        self.assertEqual(payment.method, "bank_transfer")
