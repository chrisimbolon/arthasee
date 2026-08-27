# =============================================================================
# === backend/apps/purchasing/tests.py ===
# =============================================================================
"""
Sprint 3 — model-layer tests (Stage 1) plus real event/posting proof
(Stage 2). No HTTP endpoints exist yet — that's a later stage.
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from apps.accounting.models import Account
from apps.authentication.models import CustomUser
from apps.inventory.models import Part, StockAdjustment
from apps.organizations.models import Organization, OrganizationMembership
from apps.payments.models import SupplierPayment
from django.core.management import call_command
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from . import reports
from .models import (GoodsReceivedNote, PurchaseOrder, PurchaseReturn,
                     QuickPurchase, Supplier, SupplierInvoice)


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

    def _create_po_and_lines(self, lines, supplier=None, organization=None):
        """
        lines: [{"part": <Part>, "quantity": Decimal, "unit_cost": Decimal}, ...]
        Real, shared prerequisite every receive() call now needs —
        creates one real PO with matching line items, returns
        (purchase_order, {part_id: po_line_item}) so callers can build
        the GRN's own lines referencing the right po_line_item per
        part. Every subclass's own _receive()-style helper builds on
        this rather than duplicating PO-creation boilerplate.
        """
        po = PurchaseOrder.create_order(
            organization=organization or self.org, supplier=supplier or self.supplier,
            order_date="2026-08-14",
            lines=[
                {"part": l["part"], "quantity_ordered": l["quantity"], "unit_cost": l["unit_cost"]}
                for l in lines
            ],
        )
        po_lines_by_part = {li.part_id: li for li in po.line_items.all()}
        return po, po_lines_by_part


class GoodsReceivedNoteTests(PurchasingModelTestBase):

    def _receive(self, lines, received_by=None):
        po, po_lines_by_part = self._create_po_and_lines(lines)
        return GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[
                {
                    "purchase_order_line_item": po_lines_by_part[l["part"].id],
                    "quantity": l["quantity"], "unit_cost": l["unit_cost"],
                }
                for l in lines
            ],
            received_by=received_by,
        )

    def test_receive_creates_grn_with_sequential_number(self):
        grn = self._receive(
            lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
            received_by=self.owner,
        )
        self.assertEqual(grn.number, "GRN/00001")
        self.assertEqual(grn.sequence_number, 1)

    def test_receive_increments_part_stock_via_real_stock_adjustment(self):
        self.assertEqual(self.part_a.current_stock, Decimal("0"))

        self._receive(lines=[{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}])

        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("10.00"))

        adjustment = StockAdjustment.objects.get(part=self.part_a)
        self.assertEqual(adjustment.reason, "restock")
        self.assertEqual(adjustment.quantity_change, Decimal("10.00"))

    def test_receive_with_multiple_lines_updates_each_part_independently(self):
        self._receive(lines=[
            {"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")},
            {"part": self.part_b, "quantity": Decimal("4.00"), "unit_cost": Decimal("40000.00")},
        ])
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("10.00"))
        self.assertEqual(self.part_b.current_stock, Decimal("9.00"))  # 5 existing + 4 received

    def test_total_cost_aggregates_correctly_across_lines(self):
        grn = self._receive(lines=[
            {"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")},
            {"part": self.part_b, "quantity": Decimal("4.00"), "unit_cost": Decimal("40000.00")},
        ])
        self.assertEqual(grn.total_cost, Decimal("610000.00"))

    def test_unit_cost_is_independent_of_part_unit_price(self):
        grn = self._receive(lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("50000.00")}])
        self.part_a.refresh_from_db()
        self.assertEqual(grn.line_items.first().unit_cost, Decimal("50000.00"))
        self.assertEqual(self.part_a.unit_price, Decimal("75000.00"))  # untouched

    def test_receive_requires_at_least_one_line(self):
        po, _ = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}]
        )
        with self.assertRaises(ValueError):
            GoodsReceivedNote.receive(organization=self.org, purchase_order=po, lines=[])

    def test_grn_numbers_are_scoped_per_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain Purchasing")
        # Real requirement, 26 Aug 2026 — GoodsReceivedNote.receive()
        # now hard-checks AccountingPeriod.assert_open_for_posting()
        # synchronously, before writing anything. This bare other_org
        # never had a COA/period at all — harmless before that check
        # existed, a real, correct 400 now, so it needs seeding too.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        self._receive(lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}])

        other_po = PurchaseOrder.create_order(
            organization=other_org, supplier=other_supplier, order_date="2026-08-14",
            lines=[{"part": other_part, "quantity_ordered": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, purchase_order=other_po,
            lines=[{
                "purchase_order_line_item": other_po.line_items.first(),
                "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00"),
            }],
        )
        self.assertEqual(other_grn.number, "GRN/00001")  # not 00002 — separate sequence

    def test_receiving_more_than_po_quantity_is_hard_blocked(self):
        """
        The real, confirmed guardrail: a PO is a spend ceiling, not a
        suggestion. Over-receiving must be blocked outright, not
        silently allowed or merely warned about.
        """
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        with self.assertRaises(ValueError):
            GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po_lines[self.part_a.id],
                    "quantity": Decimal("11.00"), "unit_cost": Decimal("45000.00"),
                }],
            )

    def test_receiving_a_part_not_on_the_po_is_hard_blocked(self):
        """
        The real, confirmed second guardrail: every GRN line must
        trace back to an authorized PO line. A part from a DIFFERENT
        real PO must not be quietly foldable into this delivery.
        """
        po1, _ = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        po2, po2_lines = self._create_po_and_lines(
            [{"part": self.part_b, "quantity": Decimal("5.00"), "unit_cost": Decimal("40000.00")}]
        )
        with self.assertRaises(ValueError):
            GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po1,
                lines=[{
                    "purchase_order_line_item": po2_lines[self.part_b.id],
                    "quantity": Decimal("1.00"), "unit_cost": Decimal("40000.00"),
                }],
            )

    def test_partial_receipt_sets_po_status_partially_received(self):
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po_lines[self.part_a.id],
                "quantity": Decimal("6.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        po.refresh_from_db()
        self.assertEqual(po.status, "PARTIALLY_RECEIVED")

    def test_completing_all_lines_across_two_deliveries_sets_po_fully_received(self):
        """
        Real proof of the exact scenario verified by hand before the
        status-recompute logic was written: a partial delivery, then
        a second delivery completing it, correctly landing on
        FULLY_RECEIVED — not just "the last delivery's own lines are
        complete," but every line on the PO, across BOTH deliveries.
        """
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        po_line = po_lines[self.part_a.id]
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{"purchase_order_line_item": po_line, "quantity": Decimal("6.00"), "unit_cost": Decimal("45000.00")}],
        )
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{"purchase_order_line_item": po_line, "quantity": Decimal("4.00"), "unit_cost": Decimal("45000.00")}],
        )
        po.refresh_from_db()
        self.assertEqual(po.status, "FULLY_RECEIVED")

    def test_cannot_receive_against_a_cancelled_po(self):
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        po.cancel()
        with self.assertRaises(ValueError):
            GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po_lines[self.part_a.id],
                    "quantity": Decimal("1.00"), "unit_cost": Decimal("45000.00"),
                }],
            )

class PurchaseOrderTests(PurchasingModelTestBase):
    """New — real coverage for PurchaseOrder's own lifecycle, not
    just its effect on GoodsReceivedNote.receive()."""

    def test_create_order_defaults_to_ordered_status(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        self.assertEqual(po.status, "ORDERED")
        self.assertEqual(po.number, "PO/00001")

    def test_create_order_can_start_as_draft_when_explicitly_requested(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
            status=PurchaseOrder.Status.DRAFT,
        )
        self.assertEqual(po.status, "DRAFT")

    def test_cancel_succeeds_when_nothing_received_yet(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        po.cancel()
        self.assertEqual(po.status, "CANCELLED")

    def test_cancel_blocked_once_anything_has_been_received(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("1.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        po.refresh_from_db()
        with self.assertRaises(ValueError):
            po.cancel()

    def test_amend_quantity_cannot_drop_below_already_received(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        po_line = po.line_items.first()
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{"purchase_order_line_item": po_line, "quantity": Decimal("6.00"), "unit_cost": Decimal("45000.00")}],
        )
        po_line.refresh_from_db()
        with self.assertRaises(ValueError):
            po_line.amend_quantity(Decimal("5.00"))  # below the 6 already received

    def test_amend_quantity_allows_raising_the_ceiling(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        po_line = po.line_items.first()
        po_line.amend_quantity(Decimal("15.00"))
        self.assertEqual(po_line.quantity_outstanding, Decimal("15.00"))

class SupplierInvoiceTests(PurchasingModelTestBase):

    def _receive(self, cost=Decimal("450000.00")):
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00")}]
        )
        return GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po_lines[self.part_a.id],
                "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00"),
            }],
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
        # Same real requirement as the GRN fix above — SupplierInvoice.
        # record() now hard-checks the period too.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
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
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": quantity, "unit_cost": unit_cost}]
        )
        return GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po_lines[self.part_a.id],
                "quantity": quantity, "unit_cost": unit_cost,
            }],
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

    def test_return_blocked_if_grn_already_has_paid_supplier_invoice(self):
        """
        The real Case-C guard — the boundary that's still standing
        after Case B shipped. An UNPAID invoice no longer blocks a
        return on its own (that's Case B, correctly allowed now) —
        only a PAID one does, since the payable has already been
        settled and a reversal at that point would be silently
        wrong. Renamed from the old test name (which described the
        pre-Case-B world, where ANY invoice blocked) to match what
        this test actually proves now.
        """
        grn = self._receive()
        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("450000.00"), invoice_date="2026-08-09",
            goods_received_notes=[grn],
        )
        invoice.status = "PAID"
        invoice.save(update_fields=["status"])

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
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00")}]
        )
        with self.captureOnCommitCallbacks(execute=True):
            GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po_lines[self.part_a.id],
                    "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
                }],
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
        po, po_lines = self._create_po_and_lines(
            [{"part": self.part_a, "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00")}]
        )
        with self.captureOnCommitCallbacks(execute=True):
            return GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po_lines[self.part_a.id],
                    "quantity": Decimal("10.00"), "unit_cost": cost / Decimal("10.00"),
                }],
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

    def _create_po_via_api(self, part=None, quantity="10.00", unit_cost="45000.00"):
        """
        Real shared prerequisite every GRN test now needs — creates a
        PO through the actual HTTP endpoint (not the model layer
        directly), matching what a real user does. No
        captureOnCommitCallbacks wrapper here — PurchaseOrder.create_order()
        deliberately publishes no domain event (a PO is a commitment,
        not yet an economic transaction), so there's nothing for
        on_commit to fire.
        """
        part = part or self.part
        resp = self.client.post("/api/purchase-orders/", {
            "supplier": str(self.supplier.id), "order_date": "2026-08-14",
            "lines": [{"part": str(part.id), "quantity_ordered": quantity, "unit_cost": unit_cost}],
        }, format="json")
        return resp.data["purchase_order"]


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

class PurchaseOrderAPITests(PurchasingAPITestBase):

    def test_create_purchase_order_defaults_to_ordered(self):
        po = self._create_po_via_api()
        self.assertEqual(po["status"], "ORDERED")
        self.assertEqual(po["number"], "PO/00001")

    def test_create_purchase_order_rejects_cross_tenant_part(self):
        other_org = Organization.objects.create(name="Bengkel Lain PO Part")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        resp = self.client.post("/api/purchase-orders/", {
            "supplier": str(self.supplier.id), "order_date": "2026-08-14",
            "lines": [{"part": str(other_part.id), "quantity_ordered": "1.00", "unit_cost": "1000.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(PurchaseOrder.objects.exists())

    def test_cancel_purchase_order_via_api(self):
        po = self._create_po_via_api()
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["purchase_order"]["status"], "CANCELLED")

    def test_cancel_blocked_via_api_once_received(self):
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "1.00", "unit_cost": "45000.00"}],
            }, format="json")
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_amend_quantity_via_api(self):
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]
        resp = self.client.post(f"/api/purchase-order-line-items/{po_line_id}/amend/", {
            "quantity_ordered": "20.00",
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["purchase_order_line_item"]["quantity_ordered"], "20.00")

    def test_receiving_more_than_po_via_api_is_blocked(self):
        po = self._create_po_via_api(quantity="10.00")
        po_line_id = po["line_items"][0]["id"]
        resp = self.client.post("/api/goods-received-notes/", {
            "purchase_order": po["id"],
            "lines": [{"purchase_order_line_item": po_line_id, "quantity": "11.00", "unit_cost": "45000.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

class GoodsReceivedNoteAPITests(PurchasingAPITestBase):

    def test_create_grn_via_api_posts_real_journal_entry(self):
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"))

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        self.assertEqual(inventory.balance(), Decimal("450000.00"))
        self.assertEqual(accrued.balance(), Decimal("450000.00"))

    def test_create_grn_rejects_cross_tenant_purchase_order_line_item(self):
        """
        The real proof the UUIDField-not-PrimaryKeyRelatedField
        design decision still holds at this layer — real equivalent
        of the original "cross-tenant part" concern. `part` is no
        longer a direct GRN input at all (it's derived through
        purchase_order_line_item) — the real boundary to prove now is
        that referencing another shop's PurchaseOrderLineItem, even
        against an otherwise valid OWN PurchaseOrder, is structurally
        impossible, not just discouraged.
        """
        other_org = Organization.objects.create(name="Bengkel Lain GRN Part")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Org Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_po = PurchaseOrder.create_order(
            organization=other_org, supplier=other_supplier, order_date="2026-08-14",
            lines=[{"part": other_part, "quantity_ordered": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )

        my_po = self._create_po_via_api()

        resp = self.client.post("/api/goods-received-notes/", {
            "purchase_order": my_po["id"],
            "lines": [{
                "purchase_order_line_item": str(other_po.line_items.first().id),
                "quantity": "1.00", "unit_cost": "1000.00",
            }],
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(GoodsReceivedNote.objects.exists())  # nothing partial got created

    def test_create_grn_rejects_cross_tenant_purchase_order(self):
        """
        Real equivalent of the original "cross-tenant supplier"
        concern. `supplier` is no longer a direct GRN input at all
        (it's derived from purchase_order.supplier inside receive())
        — the real cross-tenant boundary to prove now is the PO
        reference itself.
        """
        other_org = Organization.objects.create(name="Bengkel Lain GRN Supplier")
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Org Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain 2", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_po = PurchaseOrder.create_order(
            organization=other_org, supplier=other_supplier, order_date="2026-08-14",
            lines=[{"part": other_part, "quantity_ordered": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )

        resp = self.client.post("/api/goods-received-notes/", {
            "purchase_order": str(other_po.id),
            "lines": [{
                "purchase_order_line_item": str(other_po.line_items.first().id),
                "quantity": "1.00", "unit_cost": "1000.00",
            }],
        }, format="json")

        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_b_cannot_see_org_a_goods_received_notes(self):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part, "quantity_ordered": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00"),
            }],
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
        The real end-to-end proof — order, receive goods, bill it,
        pay it, all through the actual HTTP endpoints, confirming the
        ledger is correct at every step, not just that each call
        returns the right status code.
        """
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "10.00", "unit_cost": "45000.00"}],
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
        # Same real requirement — this test calls GoodsReceivedNote.
        # receive() directly at the model layer for other_org, which
        # now needs a real period to post into.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Org Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_po = PurchaseOrder.create_order(
            organization=other_org, supplier=other_supplier, order_date="2026-08-14",
            lines=[{"part": other_part, "quantity_ordered": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, purchase_order=other_po,
            lines=[{
                "purchase_order_line_item": other_po.line_items.first(),
                "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00"),
            }],
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
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "10.00", "unit_cost": "45000.00"}],
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

    def test_return_rejects_grn_already_invoiced_and_paid(self):
        """
        Renamed to match what this now actually proves — an UNPAID
        invoice no longer blocks a return via the API either (Case B,
        correctly allowed). The real remaining boundary is Case C:
        once the invoice is genuinely PAID (via the real /pay/
        endpoint, not just a direct field flip, so this exercises the
        actual payment flow too), the return must still be rejected.
        """
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "10.00", "unit_cost": "45000.00"}],
            }, format="json")
        grn_data = grn_resp.data["goods_received_note"]

        with self.captureOnCommitCallbacks(execute=True):
            invoice_resp = self.client.post("/api/supplier-invoices/", {
                "supplier": str(self.supplier.id),
                "amount": "450000.00",
                "invoice_date": "2026-08-09",
                "goods_received_note_ids": [grn_data["id"]],
            }, format="json")
        supplier_invoice_id = invoice_resp.data["supplier_invoice"]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"/api/supplier-invoices/{supplier_invoice_id}/pay/",
                {"method": "bank_transfer"}, format="json",
            )

        resp = self.client.post("/api/purchase-returns/", {
            "goods_received_note": grn_data["id"],
            "reason": "Terlambat",
            "lines": [{"grn_line_item": grn_data["line_items"][0]["id"], "quantity": "1.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_return_rejects_cross_tenant_grn(self):
        other_org = Organization.objects.create(name="Bengkel Lain Return")
        # Same real requirement — GoodsReceivedNote.receive() is
        # called directly at the model layer to set up this test's
        # own other_grn fixture.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_po = PurchaseOrder.create_order(
            organization=other_org, supplier=other_supplier, order_date="2026-08-14",
            lines=[{"part": other_part, "quantity_ordered": Decimal("5.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_grn = GoodsReceivedNote.receive(
            organization=other_org, purchase_order=other_po,
            lines=[{
                "purchase_order_line_item": other_po.line_items.first(),
                "quantity": Decimal("5.00"), "unit_cost": Decimal("1000.00"),
            }],
        )

        resp = self.client.post("/api/purchase-returns/", {
            "goods_received_note": str(other_grn.id),
            "reason": "Tidak sah",
            "lines": [{"grn_line_item": str(other_grn.line_items.first().id), "quantity": "1.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(PurchaseReturn.objects.exists())

    def test_org_b_cannot_see_org_a_purchase_returns(self):
        po = self._create_po_via_api()
        po_line_id = po["line_items"][0]["id"]

        with self.captureOnCommitCallbacks(execute=True):
            grn_resp = self.client.post("/api/goods-received-notes/", {
                "purchase_order": po["id"],
                "lines": [{"purchase_order_line_item": po_line_id, "quantity": "5.00", "unit_cost": "1000.00"}],
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

class PurchaseReturnClassificationTests(PurchasingModelTestBase):
    """
    Real coverage for Case B (return after an unpaid invoice) and the
    Case C block (return after a paid invoice), plus proof that
    Case A's own classification and posting are unaffected by this
    change. Self-contained _receive() helper — deliberately not
    reused from PurchaseReturnTests, to avoid drifting out of sync
    with that class's own exact current shape.
    """

    def _receive(self, quantity=Decimal("10.00"), unit_cost=Decimal("45000.00")):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": quantity, "unit_cost": unit_cost}],
        )
        # Real bug, caught live: this was missing
        # captureOnCommitCallbacks — Django's on_commit() hooks never
        # fire inside a TestCase's own rolled-back transaction unless
        # explicitly captured, so the GoodsReceived event silently
        # never posted. Every downstream balance assertion in this
        # class was checking numbers that only ever reflected the
        # RETURN's own posting, never the original receive — a test
        # bug, not a backend bug.
        with self.captureOnCommitCallbacks(execute=True):
            grn = GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po.line_items.first(),
                    "quantity": quantity, "unit_cost": unit_cost,
                }],
            )
        return grn

    def test_case_a_return_before_invoice_is_classified_and_posts_to_accrued_inventory(self):
        """
        Regression proof — Case A's real classification and posting
        are unchanged by this whole addition. Same math already
        proven for Case A when it first shipped.
        """
        grn = self._receive(quantity=Decimal("10.00"), unit_cost=Decimal("45000.00"))
        grn_line = grn.line_items.first()

        with self.captureOnCommitCallbacks(execute=True):
            ret = PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn,
                lines=[{"grn_line_item": grn_line, "quantity": Decimal("3.00")}],
                reason="Rusak",
            )

        self.assertEqual(ret.return_classification, "BEFORE_INVOICE")

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        self.assertEqual(inventory.balance(), Decimal("315000.00"))
        self.assertEqual(accrued.balance(), Decimal("315000.00"))

    def test_case_b_return_after_unpaid_invoice_is_classified_and_posts_to_accounts_payable(self):
        """
        The real, new behavior — traced by hand across all three
        chained events (receive -> invoice -> return) before this
        assertion was written: 1301=315000, 2010=0, 2001=315000.
        """
        grn = self._receive(quantity=Decimal("10.00"), unit_cost=Decimal("45000.00"))
        grn_line = grn.line_items.first()

        with self.captureOnCommitCallbacks(execute=True):
            SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("450000.00"), invoice_date="2026-08-14",
                goods_received_notes=[grn],
            )

        with self.captureOnCommitCallbacks(execute=True):
            ret = PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn,
                lines=[{"grn_line_item": grn_line, "quantity": Decimal("3.00")}],
                reason="Rusak, sudah ditagih tapi belum dibayar",
            )

        self.assertEqual(ret.return_classification, "AFTER_INVOICE_UNPAID")

        inventory = Account.objects.get(organization=self.org, code="1301")
        accrued   = Account.objects.get(organization=self.org, code="2010")
        ap        = Account.objects.get(organization=self.org, code="2001")

        self.assertEqual(accrued.balance(), Decimal("0.00"))    # fully cleared by the invoice
        self.assertEqual(inventory.balance(), Decimal("315000.00"))  # 450000 - 135000
        self.assertEqual(ap.balance(), Decimal("315000.00"))          # 450000 - 135000

    def test_case_c_return_after_paid_invoice_is_blocked(self):
        """
        The real, deliberate boundary — a return against a PAID
        invoice must be blocked outright, not silently misclassified
        or allowed under either existing case. Directly sets
        invoice.status="PAID" rather than exercising the full real
        /pay/ endpoint — this test is about PurchaseReturn's own
        guard reading that status, not about proving the payment flow
        itself (already covered elsewhere).
        """
        grn = self._receive(quantity=Decimal("10.00"), unit_cost=Decimal("45000.00"))
        grn_line = grn.line_items.first()

        with self.captureOnCommitCallbacks(execute=True):
            invoice = SupplierInvoice.record(
                organization=self.org, supplier=self.supplier,
                amount=Decimal("450000.00"), invoice_date="2026-08-14",
                goods_received_notes=[grn],
            )
        invoice.status = "PAID"
        invoice.save(update_fields=["status"])

        with self.assertRaises(ValueError):
            PurchaseReturn.create_return(
                organization=self.org, goods_received_note=grn,
                lines=[{"grn_line_item": grn_line, "quantity": Decimal("1.00")}],
                reason="Terlambat, sudah dibayar",
            )
        self.assertFalse(PurchaseReturn.objects.exists())

class SupplierReliabilityReportTests(PurchasingModelTestBase):
    """
    Real coverage for supplier_reliability() — the on-time judgment
    (fully received AND has a real expected_date, judged by the
    LATEST GRN's own received_at against expected_date), the return-
    rate calculation, and the "no real activity -> excluded entirely"
    rule. All verified by hand before the function was originally
    written; these are the same scenarios as permanent tests.

    GoodsReceivedNote.receive() sets received_at to the real moment
    it's called — always "today" during a test run — so "on time" is
    tested by setting expected_date to tomorrow, "late" by setting it
    to yesterday, rather than trying to control received_at directly.
    """

    def _create_po(self, expected_date=None):
        po = PurchaseOrder.create_order(
            organization=self.org, supplier=self.supplier, order_date="2026-08-14",
            lines=[{"part": self.part_a, "quantity_ordered": Decimal("10.00"), "unit_cost": Decimal("45000.00")}],
        )
        if expected_date is not None:
            po.expected_date = expected_date
            po.save(update_fields=["expected_date"])
        return po

    def test_on_time_po_counts_correctly(self):
        po = self._create_po(expected_date=date.today() + timedelta(days=1))
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        row = data["suppliers"][0]
        self.assertEqual(row["total_pos_judged"], 1)
        self.assertEqual(row["on_time_pos"], 1)
        self.assertEqual(row["on_time_rate"], Decimal("100"))

    def test_late_po_counts_correctly(self):
        po = self._create_po(expected_date=date.today() - timedelta(days=1))
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        row = data["suppliers"][0]
        self.assertEqual(row["total_pos_judged"], 1)
        self.assertEqual(row["on_time_pos"], 0)
        self.assertEqual(row["on_time_rate"], Decimal("0"))

    def test_late_po_judged_correctly_even_at_early_morning_wib(self):
        """
        Real bug, found live: `g.received_at.date()` used to extract the
        UTC calendar date directly, not the local (WIB) one. At any time
        between roughly 00:00-07:00 WIB, UTC is still the PREVIOUS day —
        silently rolling a real "today" delivery back to "yesterday" for
        comparison purposes, which could misjudge a genuinely LATE
        delivery as on-time. A normal test can't reproduce this by
        accident (it depends on real wall-clock time when the suite
        happens to run) — this fakes `timezone.now()` to the exact real
        trigger window (03:05 WIB / 20:05 UTC the day before) so the bug
        is provably fixed, not just "didn't reproduce this time."
        """
        # 03:05 WIB, 24 Aug 2026 == 20:05 UTC, 23 Aug 2026.
        fake_now_utc = datetime(2026, 8, 23, 20, 5, 0, tzinfo=dt_timezone.utc)

        with patch("django.utils.timezone.now", return_value=fake_now_utc):
            # expected_date is a real LOCAL calendar date a staff member
            # would have entered — "yesterday" relative to LOCAL today
            # (24 Aug WIB), i.e. 23 Aug. Before the fix, received_at's
            # UTC date (also 23 Aug, per the mocked clock above) would
            # collide with this and wrongly count as on-time.
            po = self._create_po(expected_date=date(2026, 8, 23))
            GoodsReceivedNote.receive(
                organization=self.org, purchase_order=po,
                lines=[{
                    "purchase_order_line_item": po.line_items.first(),
                    "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
                }],
            )

        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date(2026, 8, 24))
        row = data["suppliers"][0]
        self.assertEqual(row["total_pos_judged"], 1)
        # The real delivery happened at 03:05 on 24 Aug LOCAL time — one
        # full day after the 23 Aug expected_date — so this must be
        # judged LATE, regardless of what UTC calendar date the same
        # instant happens to fall on.
        self.assertEqual(row["on_time_pos"], 0)
        self.assertEqual(row["on_time_rate"], Decimal("0"))

    def test_po_with_no_expected_date_excluded_from_judgment_but_counts_value(self):
        po = self._create_po(expected_date=None)
        GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        row = data["suppliers"][0]
        self.assertEqual(row["total_pos_judged"], 0)
        self.assertIsNone(row["on_time_rate"])
        self.assertEqual(row["total_received_value"], Decimal("450000.00"))

    def test_still_open_po_produces_no_activity_row(self):
        """
        A PO created but never received stays ORDERED — not
        FULLY_RECEIVED — so it must never be judged. With no GRN at
        all, it also contributes zero received value, so the
        supplier has genuinely zero real activity and is excluded
        entirely, same rule as a supplier never touched at all.
        """
        self._create_po(expected_date=date.today() + timedelta(days=1))
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        self.assertEqual(len(data["suppliers"]), 0)

    def test_supplier_with_zero_activity_is_excluded_entirely(self):
        Supplier.objects.create(organization=self.org, name="Unused Supplier")
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        names = [s["supplier_name"] for s in data["suppliers"]]
        self.assertNotIn("Unused Supplier", names)

    def test_return_rate_reflects_a_real_return(self):
        po = self._create_po(expected_date=date.today() + timedelta(days=1))
        grn = GoodsReceivedNote.receive(
            organization=self.org, purchase_order=po,
            lines=[{
                "purchase_order_line_item": po.line_items.first(),
                "quantity": Decimal("10.00"), "unit_cost": Decimal("45000.00"),
            }],
        )
        PurchaseReturn.create_return(
            organization=self.org, goods_received_note=grn,
            lines=[{"grn_line_item": grn.line_items.first(), "quantity": Decimal("2.00")}],
            reason="Barang cacat",
        )
        data = reports.supplier_reliability(self.org, since=date(2026, 1, 1), as_of=date.today())
        row = data["suppliers"][0]
        self.assertEqual(row["total_returned_value"], Decimal("90000.00"))  # 2 * 45000
        self.assertEqual(row["return_rate"].quantize(Decimal("1")), Decimal("20"))  # 90000/450000*100

class QuickPurchaseTests(PurchasingModelTestBase):
    """
    Made's own confirmed exception, 25 Aug meeting — a real,
    immediate spot purchase for HARIAN/MINGGUAN parts, no
    PurchaseOrder required. Proves the stock/cost side
    (StockAdjustment, Part.cost_price "Last Cost") independently of
    the GL posting side — see QuickPurchaseEventTests below.
    """

    def test_record_creates_sequential_number(self):
        qp = QuickPurchase.record(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("2.00"), "unit_cost": Decimal("70000.00")}],
        )
        self.assertEqual(qp.number, "QP/00001")
        self.assertEqual(qp.sequence_number, 1)

    def test_record_increases_stock_via_real_stock_adjustment(self):
        self.assertEqual(self.part_a.current_stock, Decimal("0"))
        QuickPurchase.record(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("3.00"), "unit_cost": Decimal("70000.00")}],
        )
        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("3.00"))

        adjustment = StockAdjustment.objects.get(part=self.part_a)
        # reason="restock", NOT "correction" — a real incoming
        # purchase is a restock, same real-world event
        # GoodsReceivedNoteLineItem already labels this way.
        # "correction" is this codebase's own established label for
        # fixing a miscount (Stock Opname); this test is the real
        # regression guard for that deliberate choice.
        self.assertEqual(adjustment.reason, "restock")
        self.assertEqual(adjustment.quantity_change, Decimal("3.00"))

    def test_record_updates_part_cost_price_last_cost(self):
        self.assertEqual(self.part_a.cost_price, Decimal("0"))
        QuickPurchase.record(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("2.00"), "unit_cost": Decimal("70000.00")}],
        )
        self.part_a.refresh_from_db()
        self.assertEqual(self.part_a.cost_price, Decimal("70000.00"))

    def test_multi_line_purchase_updates_each_part_independently(self):
        """
        Made's own confirmed call — staff often buy a few different
        consumables on one real receipt during a quick run, not just
        one part at a time.
        """
        qp = QuickPurchase.record(
            organization=self.org, supplier=self.supplier,
            lines=[
                {"part": self.part_a, "quantity": Decimal("2.00"), "unit_cost": Decimal("70000.00")},
                {"part": self.part_b, "quantity": Decimal("1.00"), "unit_cost": Decimal("55000.00")},
            ],
        )
        self.part_a.refresh_from_db()
        self.part_b.refresh_from_db()
        self.assertEqual(self.part_a.current_stock, Decimal("2.00"))
        self.assertEqual(self.part_b.current_stock, Decimal("6.00"))  # 5 existing + 1
        self.assertEqual(self.part_a.cost_price, Decimal("70000.00"))
        self.assertEqual(self.part_b.cost_price, Decimal("55000.00"))
        self.assertEqual(qp.total_cost, Decimal("195000.00"))  # 2*70000 + 1*55000

    def test_record_requires_at_least_one_line(self):
        with self.assertRaises(ValueError):
            QuickPurchase.record(organization=self.org, supplier=self.supplier, lines=[])

    def test_quick_purchase_numbers_are_scoped_per_organization(self):
        QuickPurchase.record(
            organization=self.org, supplier=self.supplier,
            lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        other_org = Organization.objects.create(name="Bengkel Lain QuickPurchase")
        # Same real requirement — QuickPurchase.record() is called
        # directly at the model layer for other_org here.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_supplier = Supplier.objects.create(organization=other_org, name="Toko Lain")
        other_part = Part.objects.create(
            organization=other_org, name="Part Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        other_qp = QuickPurchase.record(
            organization=other_org, supplier=other_supplier,
            lines=[{"part": other_part, "quantity": Decimal("1.00"), "unit_cost": Decimal("1000.00")}],
        )
        self.assertEqual(other_qp.number, "QP/00001")  # separate sequence, not 00002


class QuickPurchaseEventTests(PurchasingModelTestBase):
    """
    Real GL proof — Dr Inventory (1301) / Cr Cash (1001) or Bank
    (1101) depending on payment_method. Same standard as
    GoodsReceivedEventTests above: proves the actual journal entry,
    not just that the model layer runs without error. This is the
    highest-value test in this whole batch — brand-new, money-moving
    GL logic, checked with the same rigor as everything else in this
    file, right after a real GL inconsistency was found and fixed
    elsewhere in this same sprint.
    """

    def test_cash_purchase_posts_inventory_and_cash(self):
        with self.captureOnCommitCallbacks(execute=True):
            QuickPurchase.record(
                organization=self.org, supplier=self.supplier,
                lines=[{"part": self.part_a, "quantity": Decimal("2.00"), "unit_cost": Decimal("70000.00")}],
                payment_method="cash",
            )
        inventory = Account.objects.get(organization=self.org, code="1301")
        cash      = Account.objects.get(organization=self.org, code="1001")
        # 2 * 70000 = 140000 — verified by hand before this assertion
        # was written. Cash is credited, so its balance goes negative
        # — same sign convention already proven by
        # SupplierInvoiceAPITests.test_full_round_trip_receive_invoice_and_pay's
        # own bank.balance() assertion.
        self.assertEqual(inventory.balance(), Decimal("140000.00"))
        self.assertEqual(cash.balance(), Decimal("-140000.00"))

    def test_bank_purchase_posts_inventory_and_bank(self):
        with self.captureOnCommitCallbacks(execute=True):
            QuickPurchase.record(
                organization=self.org, supplier=self.supplier,
                lines=[{"part": self.part_a, "quantity": Decimal("1.00"), "unit_cost": Decimal("55000.00")}],
                payment_method="bank",
            )
        inventory = Account.objects.get(organization=self.org, code="1301")
        bank      = Account.objects.get(organization=self.org, code="1101")
        self.assertEqual(inventory.balance(), Decimal("55000.00"))
        self.assertEqual(bank.balance(), Decimal("-55000.00"))

    def test_multi_line_purchase_posts_the_aggregated_total(self):
        """
        Real proof the posting uses the SUMMED total across every
        line, not a per-line posting — matches GoodsReceived's own
        aggregated-total shape, not PartConsumed's per-line shape.
        """
        with self.captureOnCommitCallbacks(execute=True):
            QuickPurchase.record(
                organization=self.org, supplier=self.supplier,
                lines=[
                    {"part": self.part_a, "quantity": Decimal("2.00"), "unit_cost": Decimal("70000.00")},
                    {"part": self.part_b, "quantity": Decimal("1.00"), "unit_cost": Decimal("55000.00")},
                ],
                payment_method="cash",
            )
        inventory = Account.objects.get(organization=self.org, code="1301")
        cash      = Account.objects.get(organization=self.org, code="1001")
        self.assertEqual(inventory.balance(), Decimal("195000.00"))
        self.assertEqual(cash.balance(), Decimal("-195000.00"))


class QuickPurchaseAPITests(PurchasingAPITestBase):

    def test_create_quick_purchase_via_api_posts_real_journal_entry(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post("/api/quick-purchases/", {
                "supplier": str(self.supplier.id),
                "payment_method": "cash",
                "lines": [{"part": str(self.part.id), "quantity": "2.00", "unit_cost": "70000.00"}],
            }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("2.00"))
        self.assertEqual(self.part.cost_price, Decimal("70000.00"))

        inventory = Account.objects.get(organization=self.org, code="1301")
        cash      = Account.objects.get(organization=self.org, code="1001")
        self.assertEqual(inventory.balance(), Decimal("140000.00"))
        self.assertEqual(cash.balance(), Decimal("-140000.00"))

    def test_create_quick_purchase_rejects_cross_tenant_part(self):
        other_org = Organization.objects.create(name="Bengkel Lain QP Part")
        other_part = Part.objects.create(
            organization=other_org, name="Part Org Lain", unit="pcs",
            unit_price=Decimal("10000.00"), current_stock=Decimal("0"),
        )
        resp = self.client.post("/api/quick-purchases/", {
            "supplier": str(self.supplier.id),
            "lines": [{"part": str(other_part.id), "quantity": "1.00", "unit_cost": "1000.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(QuickPurchase.objects.exists())

    def test_create_quick_purchase_rejects_cross_tenant_supplier(self):
        other_org = Organization.objects.create(name="Bengkel Lain QP Supplier")
        other_supplier = Supplier.objects.create(organization=other_org, name="Toko Lain")
        resp = self.client.post("/api/quick-purchases/", {
            "supplier": str(other_supplier.id),
            "lines": [{"part": str(self.part.id), "quantity": "1.00", "unit_cost": "1000.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(QuickPurchase.objects.exists())

    def test_org_b_cannot_see_org_a_quick_purchases(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/quick-purchases/", {
                "supplier": str(self.supplier.id),
                "lines": [{"part": str(self.part.id), "quantity": "1.00", "unit_cost": "1000.00"}],
            }, format="json")

        other_org = Organization.objects.create(name="Bengkel Lain QP List")
        other_owner = CustomUser.objects.create_user(
            email="owner.otherorg.qp@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=other_org, user=other_owner, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=other_owner)

        resp = self.client.get("/api/quick-purchases/")
        self.assertEqual(resp.data["quick_purchases"], [])


class SupplierInvoiceAttachmentAPITests(PurchasingAPITestBase):
    """
    Made's own confirmed request, 25 Aug meeting — a real file upload
    round trip. Proves the file is actually retrievable afterward,
    not just that the endpoint returns 200 — same "prove the real
    effect, not just the status code" discipline as every GL-posting
    test in this file.
    """

    def test_upload_attachment_round_trip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("100000.00"), invoice_date="2026-08-25",
        )
        fake_file = SimpleUploadedFile(
            "invoice.pdf", b"%PDF-1.4 fake content", content_type="application/pdf",
        )
        resp = self.client.post(
            f"/api/supplier-invoices/{invoice.id}/attachment/",
            {"attachment": fake_file}, format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        invoice.refresh_from_db()
        self.assertTrue(invoice.attachment.name)
        self.assertIn("invoice", invoice.attachment.name)

    def test_upload_attachment_rejects_missing_file(self):
        invoice = SupplierInvoice.record(
            organization=self.org, supplier=self.supplier,
            amount=Decimal("100000.00"), invoice_date="2026-08-25",
        )
        resp = self.client.post(f"/api/supplier-invoices/{invoice.id}/attachment/", {}, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_attachment_rejects_cross_tenant_invoice(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        other_org = Organization.objects.create(name="Bengkel Lain SINV Attachment")
        # Same real requirement — SupplierInvoice.record() is called
        # directly at the model layer to set up this test's own
        # other_invoice fixture.
        call_command("seed_coa", organization=str(other_org.id), verbosity=0)
        other_supplier = Supplier.objects.create(organization=other_org, name="Supplier Lain")
        other_invoice = SupplierInvoice.record(
            organization=other_org, supplier=other_supplier,
            amount=Decimal("50000.00"), invoice_date="2026-08-25",
        )
        fake_file = SimpleUploadedFile("invoice.pdf", b"content", content_type="application/pdf")
        resp = self.client.post(
            f"/api/supplier-invoices/{other_invoice.id}/attachment/",
            {"attachment": fake_file}, format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)