"""
Phase 21, Task C1 (22 Oct 2026) — Made's note, 12 Sep: "Waktu invoice di
posisi draft, masih bisa tambah & kurang ... jasa." Jasa lines on a DRAFT
invoice can be added, edited and removed; once issued (or cancelled) they
are frozen; part lines are not touched here (Task C2); and what gets posted
at issue is exactly what the lines say at that moment.
"""
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.inventory.models import PartUsage
from apps.organizations.models import Organization, OrganizationMembership
from rest_framework import status

from ..models import Invoice, InvoiceLineItem
from .test_invoicing import InvoicingAPITestBase


class DraftJasaLineTests(InvoicingAPITestBase):

    def setUp(self):
        super().setUp()
        PartUsage.objects.create(
            organization=self.org, service_record=self.service_record, part=self.part,
            quantity=Decimal("1.00"), unit_price_at_time=Decimal("250000.00"),
        )
        resp = self.client.post(
            f"/api/service-records/{self.service_record.id}/invoice/",
            {"labor_lines": [{"description": "Jasa Ganti Oli", "quantity": 1, "unit_price": 80000}]},
            format="json",
        )
        self.invoice_id = resp.data["invoice"]["id"]
        self.labor = InvoiceLineItem.objects.get(invoice_id=self.invoice_id, kind="labor")
        self.part_line = InvoiceLineItem.objects.get(invoice_id=self.invoice_id, kind="part")

    def _add(self, **payload):
        return self.client.post(f"/api/invoices/{self.invoice_id}/line-items/", payload, format="json")

    def _issue(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.patch(f"/api/invoices/{self.invoice_id}/status/", {"status": "ISSUED"}, format="json")

    def test_add_a_jasa_to_a_draft(self):
        resp = self._add(description="Spooring", quantity=1, unit_price=150000)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(resp.data["invoice"]["total"]), Decimal("480000.00"))

    def test_edit_a_jasa_on_a_draft(self):
        resp = self.client.patch(f"/api/invoices/line-items/{self.labor.id}/",
                                 {"description": "Jasa Ganti Oli + Filter", "quantity": 2, "unit_price": 90000}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.labor.refresh_from_db()
        self.assertEqual((self.labor.description, self.labor.quantity, self.labor.unit_price),
                         ("Jasa Ganti Oli + Filter", Decimal("2.00"), Decimal("90000.00")))

    def test_remove_a_jasa_from_a_draft(self):
        resp = self.client.delete(f"/api/invoices/line-items/{self.labor.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(InvoiceLineItem.objects.filter(id=self.labor.id).exists())
        self.assertEqual(Decimal(resp.data["invoice"]["total"]), Decimal("250000.00"))

    def test_part_line_is_not_editable_here(self):
        patch = self.client.patch(f"/api/invoices/line-items/{self.part_line.id}/",
                                  {"description": "x", "quantity": 1, "unit_price": 1}, format="json")
        delete = self.client.delete(f"/api/invoices/line-items/{self.part_line.id}/")
        self.assertEqual((patch.status_code, delete.status_code), (status.HTTP_409_CONFLICT, status.HTTP_409_CONFLICT))
        self.assertTrue(InvoiceLineItem.objects.filter(id=self.part_line.id).exists())

    def test_bad_input_is_rejected_and_writes_nothing(self):
        for payload, word in [
            ({"description": " ", "quantity": 1, "unit_price": 1}, "wajib"),
            ({"description": "X", "quantity": 0, "unit_price": 1}, "lebih dari 0"),
            ({"description": "X", "quantity": 1, "unit_price": -5}, "negatif"),
            ({"description": "X", "quantity": 1, "unit_price": "abc"}, "angka"),
        ]:
            resp = self._add(**payload)
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, payload)
            self.assertIn(word, resp.data["message"])
        self.assertEqual(InvoiceLineItem.objects.filter(invoice_id=self.invoice_id).count(), 2)

    def test_issued_invoice_is_frozen(self):
        self.assertEqual(self._issue().status_code, status.HTTP_200_OK)
        add = self._add(description="Spooring", quantity=1, unit_price=150000)
        patch = self.client.patch(f"/api/invoices/line-items/{self.labor.id}/",
                                  {"description": "x", "quantity": 1, "unit_price": 1}, format="json")
        delete = self.client.delete(f"/api/invoices/line-items/{self.labor.id}/")
        self.assertEqual({add.status_code, patch.status_code, delete.status_code}, {status.HTTP_409_CONFLICT})
        self.labor.refresh_from_db()
        self.assertEqual(self.labor.unit_price, Decimal("80000.00"))

    def test_model_guard_holds_even_without_the_view(self):
        invoice = Invoice.objects.get(pk=self.invoice_id)
        Invoice.objects.filter(pk=invoice.pk).update(status="CANCELLED")
        with self.assertRaisesMessage(ValueError, "tidak bisa diubah"):
            invoice.add_labor_line(description="X", quantity=1, unit_price=1)

    def test_issue_posts_the_edited_amounts(self):
        self.client.patch(f"/api/invoices/line-items/{self.labor.id}/",
                          {"description": "Jasa Ganti Oli", "quantity": 1, "unit_price": 100000}, format="json")
        self._add(description="Spooring", quantity=1, unit_price=150000)
        self._issue()
        row = Outbox.objects.get(event_type="InvoiceIssued", payload__invoice_id=self.invoice_id)
        self.assertEqual(Decimal(row.payload["service_amount"]), Decimal("250000"))
        self.assertEqual(Decimal(row.payload["parts_amount"]), Decimal("250000"))
        self.assertEqual(row.payload["line_item_count"], 3)

    def test_other_shop_cannot_touch_it(self):
        other_org = Organization.objects.create(name="Bengkel Lain C1", invoice_code="BLC1")
        other = CustomUser.objects.create_user(email="owner.c1@test.id", password="pass12345!", full_name="Lain")
        OrganizationMembership.objects.create(organization=other_org, user=other, role="owner", is_active=True)
        self.client.force_authenticate(user=other)
        self.assertEqual(self._add(description="X", quantity=1, unit_price=1).status_code, status.HTTP_404_NOT_FOUND)
        resp = self.client.delete(f"/api/invoices/line-items/{self.labor.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(InvoiceLineItem.objects.filter(id=self.labor.id).exists())
