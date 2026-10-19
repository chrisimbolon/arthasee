"""
Phase 21, Task 21.1 -- no prices on a Work Order (Made's 12 Sep 2026 note:
"Di WO tidak boleh muncul harga!").

Plain SimpleTestCase on unsaved instances: these check what the API and the
tracking payload SEND, so no database rows are needed.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from apps.customers.payload import _serialize_job_line
from apps.inventory.models import Part
from apps.service.models import Customer, Vehicle
from apps.workorders.models import (WorkOrder, WorkOrderJobLine,
                                    WorkOrderMaterialLine)
from apps.workorders.pdf import _strip_price_suffix as pdf_strip
from apps.workorders.serializers import (WorkOrderJobLineSerializer,
                                         WorkOrderMaterialLineSerializer)
from apps.workorders.text import strip_price_suffix
from apps.workorders.views import WorkOrderMasterListView


class StripPriceSuffixTests(SimpleTestCase):
    def test_strips_simple_suffix(self):
        self.assertEqual(strip_price_suffix("Tune-up (estimasi Rp 350.000)"), "Tune-up")

    def test_strips_millions_and_extra_spaces(self):
        self.assertEqual(strip_price_suffix("Overhaul mesin  (Estimasi Rp 1.500.000) "), "Overhaul mesin")

    def test_leaves_plain_text_alone(self):
        self.assertEqual(strip_price_suffix("Ganti oli mesin"), "Ganti oli mesin")

    def test_only_strips_at_the_end(self):
        text = "Cek (estimasi Rp 100.000) lalu setel rem"
        self.assertEqual(strip_price_suffix(text), text)

    def test_empty_and_none_are_safe(self):
        self.assertEqual(strip_price_suffix(""), "")
        self.assertIsNone(strip_price_suffix(None))

    def test_pdf_module_still_exposes_the_old_name(self):
        self.assertEqual(pdf_strip("Spooring (estimasi Rp 200.000)"), "Spooring")


class WorkOrderMaterialLineSerializerNoPriceTests(SimpleTestCase):
    def test_no_price_fields_in_output(self):
        line = WorkOrderMaterialLine(
            part=Part(name="Oli Mesin", unit="Liter"),
            quantity=Decimal("4"), unit_price_at_time=Decimal("55000"),
        )
        data = WorkOrderMaterialLineSerializer(line).data
        self.assertNotIn("unit_price_at_time", data)
        self.assertNotIn("subtotal", data)
        self.assertEqual(data["part_name"], "Oli Mesin")
        self.assertEqual(data["unit"], "Liter")


class WorkOrderJobLineSerializerNoPriceTests(SimpleTestCase):
    def test_old_estimate_suffix_is_stripped_on_read(self):
        line = WorkOrderJobLine(
            work_order=WorkOrder(status="IN_PROGRESS"),
            description="Tune-up (estimasi Rp 350.000)",
        )
        data = WorkOrderJobLineSerializer(line).data
        self.assertEqual(data["description"], "Tune-up")

    def test_plain_description_unchanged(self):
        line = WorkOrderJobLine(work_order=WorkOrder(status="OPEN"), description="Kuras radiator")
        self.assertEqual(WorkOrderJobLineSerializer(line).data["description"], "Kuras radiator")


class TrackingPayloadJobLineNoPriceTests(SimpleTestCase):
    def test_tracking_payload_strips_old_suffix(self):
        line = WorkOrderJobLine(description="Setel rem (estimasi Rp 200.000)")
        self.assertEqual(_serialize_job_line(line)["description"], "Setel rem")


class WorkOrderMasterListNoPriceTests(SimpleTestCase):
    def test_row_has_no_total_fields(self):
        wo = WorkOrder(
            vehicle=Vehicle(
                customer=Customer(name="Budi"), plate_number="BP 1234 XY", model="Avanza",
            ),
            number="1451", status="OPEN",
        )
        row = WorkOrderMasterListView()._serialize(wo)
        self.assertNotIn("total", row)
        self.assertNotIn("total_is_final", row)
        self.assertIsNone(row["payment_status"])
        self.assertEqual(row["vehicle_plate"], "BP 1234 XY")
