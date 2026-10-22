"""
Phase 21, Task C2 (22 Oct 2026) — parts on a DRAFT invoice (Made's note,
12 Sep: "masih bisa tambah & kurang barang"). Runs the REAL dispatch path
and checks real journal entries and real account balances, not just that
an event was registered (the Phase 20 lesson).

Fixture: a WorkOrder that used 2 x Kampas Rem (cost 150.000, price
250.000) is closed and invoiced, so before any test acts:
  COGS 5001 = 300.000, Inventory 1301 = -300.000 (no GRN in this fixture),
  stock = 8, one invoice part line (2 x 250.000) with unit_cost 150.000.
"""
from decimal import Decimal
from unittest.mock import patch

from apps.accounting.models import Account, JournalEntry
from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.inventory.models import Part, PartUsage
from apps.organizations.models import Organization, OrganizationMembership
from apps.workorders.models import WorkOrder, WorkOrderJobLine, WorkOrderMaterialLine
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from .models import Invoice, InvoiceLineItem
from .tests import InvoicingAPITestBase


class DraftPartLineTests(InvoicingAPITestBase):

    def setUp(self):
        super().setUp()
        self.part.cost_price = Decimal("150000.00")
        self.part.save(update_fields=["cost_price"])

        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic)
        with self.captureOnCommitCallbacks(execute=True):
            WorkOrderMaterialLine.objects.create(
                organization=self.org, work_order=wo, part=self.part, quantity=Decimal("2.00"),
            )
        wo.status = "IN_PROGRESS"
        wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=wo, description="Ganti kampas rem", completed_at=timezone.now(),
        )
        wo.status = "QC"
        wo.save(update_fields=["status"])
        with self.captureOnCommitCallbacks(execute=True):
            self.record = wo.close(closed_by=self.owner)

        resp = self.client.post(
            f"/api/service-records/{self.record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Ganti Kampas", "quantity": 1, "unit_price": 100000}]},
            format="json",
        )
        self.invoice_id = resp.data["invoice"]["id"]
        self.part_line = InvoiceLineItem.objects.get(invoice_id=self.invoice_id, kind="part")

    # ── helpers ──
    def _balance(self, code):
        return Account.objects.get(organization=self.org, code=code).balance()

    def _stock(self):
        self.part.refresh_from_db()
        return self.part.current_stock

    def _add(self, **payload):
        payload.setdefault("part", str(self.part.id))
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/invoices/{self.invoice_id}/part-lines/", payload, format="json")

    def _action(self, line_id, action):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/invoices/part-lines/{line_id}/{action}/")

    # ── tests ──
    def test_fixture_starting_point(self):
        self.assertEqual(self._balance("5001"), Decimal("300000"))
        self.assertEqual(self._balance("1301"), Decimal("-300000"))
        self.assertEqual(self._stock(), Decimal("8.00"))

    def test_invoice_creation_copies_the_wo_cost_onto_the_part_line(self):
        self.assertEqual(self.part_line.unit_cost, Decimal("150000.00"))
        self.assertEqual(self.part_line.unit_price, Decimal("250000.00"))

    def test_add_part_moves_stock_and_cost_and_bills_the_selling_price(self):
        resp = self._add(quantity=1)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._stock(), Decimal("7.00"))
        self.assertEqual(self._balance("5001"), Decimal("450000"))
        self.assertEqual(self._balance("1301"), Decimal("-450000"))
        new_line = InvoiceLineItem.objects.filter(invoice_id=self.invoice_id, kind="part").exclude(id=self.part_line.id).get()
        self.assertEqual((new_line.unit_price, new_line.unit_cost), (Decimal("250000.00"), Decimal("150000.00")))
        self.assertEqual(PartUsage.objects.filter(service_record=self.record).count(), 2)
        row = Outbox.objects.get(event_type="InvoicePartAdjusted")
        self.assertEqual(row.status, Outbox.Status.PROCESSED)
        self.assertTrue(JournalEntry.objects.filter(event_type="InvoicePartAdjusted", reference_event_id=row.event_id).exists())

    def test_add_part_with_a_custom_price(self):
        self._add(quantity=1, unit_price=230000)
        new_line = InvoiceLineItem.objects.filter(invoice_id=self.invoice_id, kind="part").exclude(id=self.part_line.id).get()
        self.assertEqual(new_line.unit_price, Decimal("230000.00"))
        self.assertEqual(self._balance("5001"), Decimal("450000"))  # cost, not price

    def test_return_to_stock_reverses_exactly(self):
        resp = self._action(self.part_line.id, "return")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self._stock(), Decimal("10.00"))
        self.assertEqual(self._balance("5001"), Decimal("0"))
        self.assertEqual(self._balance("1301"), Decimal("0"))
        self.assertFalse(InvoiceLineItem.objects.filter(id=self.part_line.id).exists())
        self.assertEqual(PartUsage.objects.filter(service_record=self.record).count(), 0)

    def test_add_then_return_nets_to_zero(self):
        self._add(quantity=1)
        new_line = InvoiceLineItem.objects.filter(invoice_id=self.invoice_id, kind="part").exclude(id=self.part_line.id).get()
        self._action(new_line.id, "return")
        self.assertEqual(self._balance("5001"), Decimal("300000"))
        self.assertEqual(self._balance("1301"), Decimal("-300000"))
        self.assertEqual(self._stock(), Decimal("8.00"))

    def test_return_uses_the_frozen_cost_not_todays(self):
        self.part.cost_price = Decimal("999999.00")
        self.part.save(update_fields=["cost_price"])
        self._action(self.part_line.id, "return")
        self.assertEqual(self._balance("5001"), Decimal("0"))

    def test_return_on_an_older_line_without_cost_falls_back_to_the_wo_cost(self):
        InvoiceLineItem.objects.filter(id=self.part_line.id).update(unit_cost=None)
        self.part.cost_price = Decimal("999999.00")
        self.part.save(update_fields=["cost_price"])
        self._action(self.part_line.id, "return")
        self.assertEqual(self._balance("5001"), Decimal("0"))

    def test_not_charged_keeps_the_line_at_zero_and_moves_nothing(self):
        resp = self._action(self.part_line.id, "not-charged")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.part_line.refresh_from_db()
        self.assertEqual(self.part_line.unit_price, Decimal("0.00"))
        self.assertTrue(self.part_line.description.endswith("(tidak ditagih)"))
        self.assertEqual(self._stock(), Decimal("8.00"))
        self.assertEqual(self._balance("5001"), Decimal("300000"))
        self.assertFalse(Outbox.objects.filter(event_type="InvoicePartAdjusted").exists())
        # Doing it twice does not stack the label.
        self._action(self.part_line.id, "not-charged")
        self.part_line.refresh_from_db()
        self.assertEqual(self.part_line.description.count("(tidak ditagih)"), 1)

    def test_issue_posts_the_final_lines(self):
        self._action(self.part_line.id, "not-charged")
        self._add(quantity=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"/api/invoices/{self.invoice_id}/status/", {"status": "ISSUED"}, format="json")
        row = Outbox.objects.get(event_type="InvoiceIssued", payload__invoice_id=self.invoice_id)
        self.assertEqual(Decimal(row.payload["parts_amount"]), Decimal("250000"))
        self.assertEqual(Decimal(row.payload["service_amount"]), Decimal("100000"))

    def test_issued_invoice_parts_are_frozen(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"/api/invoices/{self.invoice_id}/status/", {"status": "ISSUED"}, format="json")
        self.assertEqual(self._add(quantity=1).status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self._action(self.part_line.id, "return").status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self._action(self.part_line.id, "not-charged").status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self._stock(), Decimal("8.00"))

    def test_readiness_gate_blocks_add_and_return(self):
        blocked = Response({"success": False, "blocks": [{"code": "x", "message": "x", "action": "x"}]}, status=409)
        with patch("apps.invoicing.views.readiness_block_response", return_value=blocked):
            self.assertEqual(self._add(quantity=1).status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(self._action(self.part_line.id, "return").status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(self._stock(), Decimal("8.00"))

    def test_closed_period_blocks_and_writes_nothing(self):
        with patch("apps.accounting.models.AccountingPeriod.assert_open_for_posting",
                   side_effect=ValueError("Periode akuntansi sudah ditutup.")):
            add = self._add(quantity=1)
            ret = self._action(self.part_line.id, "return")
        self.assertEqual((add.status_code, ret.status_code), (status.HTTP_400_BAD_REQUEST, status.HTTP_400_BAD_REQUEST))
        self.assertEqual(self._stock(), Decimal("8.00"))
        self.assertTrue(InvoiceLineItem.objects.filter(id=self.part_line.id).exists())
        self.assertFalse(Outbox.objects.filter(event_type="InvoicePartAdjusted").exists())

    def test_jasa_line_cannot_use_part_actions(self):
        labor = InvoiceLineItem.objects.get(invoice_id=self.invoice_id, kind="labor")
        self.assertEqual(self._action(labor.id, "return").status_code, status.HTTP_409_CONFLICT)

    def test_other_shops_part_and_line_are_refused(self):
        other_org = Organization.objects.create(name="Bengkel Lain C2", invoice_code="BLC2")
        foreign_part = Part.objects.create(organization=other_org, name="Asing", unit="pcs", unit_price=Decimal("1"))
        self.assertEqual(self._add(part=str(foreign_part.id), quantity=1).status_code, status.HTTP_400_BAD_REQUEST)
        other = CustomUser.objects.create_user(email="owner.c2@test.id", password="pass12345!", full_name="Lain")
        OrganizationMembership.objects.create(organization=other_org, user=other, role="owner", is_active=True)
        self.client.force_authenticate(user=other)
        self.assertEqual(self._action(self.part_line.id, "return").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self._stock(), Decimal("8.00"))

    def test_model_guard_holds_without_the_view(self):
        invoice = Invoice.objects.get(pk=self.invoice_id)
        Invoice.objects.filter(pk=invoice.pk).update(status="CANCELLED")
        with self.assertRaisesMessage(ValueError, "tidak bisa diubah"):
            invoice.return_part_line(self.part_line)
        self.assertEqual(self._stock(), Decimal("8.00"))
