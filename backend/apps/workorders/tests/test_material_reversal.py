"""
Phase 21, Task 21.2b (20 Oct 2026) -- finding F6.

Removing a part from an open WO, or cancelling the WO, must reverse the
PartConsumed posting (Dr WIP / Cr Inventory) with MaterialLineReversed
(Dr Inventory / Cr WIP), not just put the stock back. These tests run the
REAL dispatch path end to end and check the real journal entry and the
real account balances -- the Phase 20 lesson: "registered" is not proof
that anything actually posts.
"""
from decimal import Decimal
from unittest.mock import patch

from apps.accounting.models import Account, JournalEntry
from apps.accounting.periods import safe_local_date
from apps.core.models import Outbox
from django.utils import timezone
from rest_framework import status

from ..models import WorkOrder, WorkOrderMaterialLine
from .test_workorders import WorkOrderAPITestBase


class MaterialLineReversalTests(WorkOrderAPITestBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def _balance(self, code):
        return Account.objects.get(organization=self.org, code=code).balance()

    def _add_line(self, quantity="2.00"):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(
                f"/api/work-orders/{self.wo.id}/material-lines/",
                {"part": str(self.part.id), "quantity": quantity}, format="json",
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        return resp.data["material_line"]["id"]

    def test_adding_a_line_moves_cost_into_wip(self):
        """Baseline: proves the fixture really posts PartConsumed, so the
        reversal tests below are checking a real posting being undone."""
        self._add_line("2.00")
        # No cost_price in the fixture -> falls back to unit_price 250.000.
        self.assertEqual(self._balance("1302"), Decimal("500000"))

    def test_delete_publishes_the_reversal_with_its_frozen_date_and_reason(self):
        line_id = self._add_line("2.00")
        self.client.delete(
            f"/api/work-orders/material-lines/{line_id}/",
            {"reason": "customer_cancelled_part"}, format="json",
        )
        row = Outbox.objects.get(event_type="MaterialLineReversed", payload__material_line_id=line_id)
        self.assertEqual(row.payload["reason"], "customer_cancelled_part")
        self.assertEqual(Decimal(row.payload["amount"]), Decimal("500000"))
        self.assertEqual(row.payload["transaction_date"], safe_local_date(timezone.now()).isoformat())

    def test_delete_really_posts_and_wip_returns_to_zero(self):
        line_id = self._add_line("2.00")
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        row = Outbox.objects.get(event_type="MaterialLineReversed", payload__material_line_id=line_id)
        self.assertEqual(row.status, Outbox.Status.PROCESSED)
        self.assertTrue(JournalEntry.objects.filter(
            event_type="MaterialLineReversed", reference_event_id=row.event_id,
        ).exists())
        self.assertEqual(self._balance("1302"), Decimal("0"))
        self.assertEqual(self._balance("1301"), Decimal("0"))
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("10.00"))

    def test_cancel_really_posts_one_reversal_per_line(self):
        self._add_line("1.00")
        self._add_line("3.00")
        self.assertEqual(self._balance("1302"), Decimal("1000000"))
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(f"/api/work-orders/{self.wo.id}/cancel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(JournalEntry.objects.filter(event_type="MaterialLineReversed").count(), 2)
        self.assertEqual(self._balance("1302"), Decimal("0"))
        self.assertEqual(self._balance("1301"), Decimal("0"))
        # Lines stay on a cancelled WO, as history.
        self.assertEqual(WorkOrderMaterialLine.objects.filter(work_order=self.wo).count(), 2)

    def test_reversal_uses_the_lines_own_frozen_cost_not_todays(self):
        line_id = self._add_line("2.00")
        self.part.cost_price = Decimal("999999")
        self.part.save(update_fields=["cost_price"])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(self._balance("1302"), Decimal("0"))

    def test_closed_period_blocks_delete_and_writes_nothing(self):
        line_id = self._add_line("2.00")
        with patch(
            "apps.accounting.models.AccountingPeriod.assert_open_for_posting",
            side_effect=ValueError("Periode akuntansi sudah ditutup."),
        ):
            resp = self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("ditutup", resp.data["message"])
        self.assertTrue(WorkOrderMaterialLine.objects.filter(id=line_id).exists())
        self.assertFalse(Outbox.objects.filter(event_type="MaterialLineReversed").exists())
        self.part.refresh_from_db()
        self.assertEqual(self.part.current_stock, Decimal("8.00"))

    def test_done_work_order_still_cannot_lose_a_line(self):
        """Unchanged guard: after close, WIP has already moved to COGS --
        a reversal against WIP would be wrong, so the 409 must stay."""
        line_id = self._add_line("1.00")
        self._ready_to_close(self.wo)
        self.wo.close(closed_by=self.owner)
        resp = self.client.delete(f"/api/work-orders/material-lines/{line_id}/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(Outbox.objects.filter(event_type="MaterialLineReversed").exists())
