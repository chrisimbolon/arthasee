"""
Phase 21, Task 21.4 (21 Oct 2026) — Daftar Jasa used on the Estimate, the
WO and the invoice suggestion:
  - an estimate jasa line can point at a Daftar Jasa item (price still the
    one typed/pre-filled, copied onto the line);
  - approving carries that link onto the WO job line;
  - a WO job line can be added from Daftar Jasa (no price on the WO);
  - a jasa added on the WO from Daftar Jasa is suggested on the invoice at
    the Daftar Jasa price for the vehicle's class (estimate price still wins
    for estimate lines — tested in apps.invoicing).
"""
from datetime import date
from decimal import Decimal

from apps.invoicing.suggestions import suggested_labor_lines
from apps.organizations.models import Organization
from apps.service.models import ServiceItem, ServiceRecord
from apps.workorders.models import WorkOrder, WorkOrderJobLine
from rest_framework import status

from ..models import Estimate, EstimateLineItem
from .test_estimates import EstimateAPITestBase


class JasaCatalogBase(EstimateAPITestBase):

    def setUp(self):
        super().setUp()
        self.vehicle.body_style = "SUV"
        self.vehicle.save(update_fields=["body_style"])
        self.ganti_oli = ServiceItem.record(
            organization=self.org, name="Jasa Ganti Oli", default_price="80000",
            class_prices={"SUV": "100000", "MPV": "110000"}, created_by=self.owner,
        )
        self.estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)


class ServiceItemPriceForVehicleTests(JasaCatalogBase):

    def test_list_with_vehicle_gives_this_vehicles_price(self):
        resp = self.client.get(f"/api/service-items/?vehicle={self.vehicle.id}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        item = resp.data["results"][0]
        self.assertEqual((item["price_for_vehicle"], item["price_source"]), ("100000.00", "class"))
        self.assertEqual(resp.data["vehicle_class"], "SUV")

    def test_vehicle_without_class_gets_the_default(self):
        self.vehicle.body_style = ""
        self.vehicle.save(update_fields=["body_style"])
        item = self.client.get(f"/api/service-items/?vehicle={self.vehicle.id}").data["results"][0]
        self.assertEqual((item["price_for_vehicle"], item["price_source"]), ("80000.00", "default"))

    def test_list_without_vehicle_has_no_vehicle_price(self):
        item = self.client.get("/api/service-items/").data["results"][0]
        self.assertIsNone(item["price_for_vehicle"])

    def test_vehicle_of_another_shop_is_a_404(self):
        from apps.service.models import Customer, Vehicle
        other_org = Organization.objects.create(name="Bengkel Lain 214", invoice_code="BL214")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=Customer.objects.create(organization=other_org, name="X"),
            plate_number="BP 99 ZZ", manufacture_year=2020, vehicle_type="Mobil", model="X",
        )
        resp = self.client.get(f"/api/service-items/?vehicle={other_vehicle.id}")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class EstimateLineFromCatalogTests(JasaCatalogBase):

    def _post(self, **extra):
        payload = {"kind": "labor", "description": "Jasa Ganti Oli", "unit_price": "95000"}
        payload.update(extra)
        return self.client.post(f"/api/estimates/{self.estimate.id}/line-items/", payload, format="json")

    def test_line_keeps_the_link_and_the_price_actually_sent(self):
        """Staff may change the pre-filled price (Chris, 21 Oct: don't lock)."""
        resp = self._post(service_item=str(self.ganti_oli.id))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        line = EstimateLineItem.objects.get(id=resp.data["line_item"]["id"])
        self.assertEqual(line.service_item, self.ganti_oli)
        self.assertEqual(line.unit_price, Decimal("95000.00"))

    def test_free_text_jasa_still_works(self):
        resp = self._post(description="Las knalpot")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(EstimateLineItem.objects.get(id=resp.data["line_item"]["id"]).service_item)

    def test_later_price_list_change_does_not_touch_the_estimate(self):
        resp = self._post(service_item=str(self.ganti_oli.id), unit_price="100000")
        self.ganti_oli.apply_edit(changed_by=self.owner, class_prices={"SUV": "150000"})
        line = EstimateLineItem.objects.get(id=resp.data["line_item"]["id"])
        self.assertEqual(line.unit_price, Decimal("100000.00"))

    def test_a_part_line_cannot_point_at_a_jasa(self):
        resp = self.client.post(f"/api/estimates/{self.estimate.id}/line-items/", {
            "kind": "part", "description": "Kampas Rem", "quantity": "1", "unit_price": "250000",
            "part": str(self.part.id), "service_item": str(self.ganti_oli.id),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_another_shops_jasa_is_rejected(self):
        other_org = Organization.objects.create(name="Bengkel Lain Jasa 214", invoice_code="BLJ214")
        foreign = ServiceItem.record(organization=other_org, name="Asing", default_price="1")
        resp = self._post(service_item=str(foreign.id))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_carries_the_link_to_the_wo_job_line(self):
        self._post(service_item=str(self.ganti_oli.id))
        work_order = self.estimate.approve(approved_by=self.owner)
        job_line = WorkOrderJobLine.objects.get(work_order=work_order)
        self.assertEqual(job_line.service_item, self.ganti_oli)


class WorkOrderJobLineFromCatalogTests(JasaCatalogBase):

    def setUp(self):
        super().setUp()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def test_job_line_can_be_added_from_daftar_jasa(self):
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/job-lines/", {
            "description": "Jasa Ganti Oli", "service_item": str(self.ganti_oli.id),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(WorkOrderJobLine.objects.get(id=resp.data["job_line"]["id"]).service_item, self.ganti_oli)

    def test_job_line_from_another_shops_jasa_is_rejected(self):
        other_org = Organization.objects.create(name="Bengkel Lain WO 214", invoice_code="BLW214")
        foreign = ServiceItem.record(organization=other_org, name="Asing", default_price="1")
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/job-lines/", {
            "description": "Asing", "service_item": str(foreign.id),
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def _invoice_suggestions(self):
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle, service_date=date.today(),
            odometer_km=66000, issue_description="Servis",
        )
        self.wo.service_record = record
        self.wo.save(update_fields=["service_record"])
        return suggested_labor_lines(record)

    def test_invoice_suggests_the_daftar_jasa_price_for_the_class(self):
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, description="Jasa Ganti Oli", service_item=self.ganti_oli,
        )
        line = self._invoice_suggestions()[0]
        self.assertEqual((line["unit_price"], line["source"], line["price_source"], line["vehicle_class"]),
                         (Decimal("100000.00"), "price_list", "class", "SUV"))

    def test_invoice_falls_back_to_the_default_price(self):
        self.vehicle.body_style = "Sedan"
        self.vehicle.save(update_fields=["body_style"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, description="Jasa Ganti Oli", service_item=self.ganti_oli,
        )
        line = self._invoice_suggestions()[0]
        self.assertEqual((line["unit_price"], line["price_source"]), (Decimal("80000.00"), "default"))

    def test_plain_wo_jasa_still_has_no_price(self):
        WorkOrderJobLine.objects.create(organization=self.org, work_order=self.wo, description="Cek rem")
        line = self._invoice_suggestions()[0]
        self.assertEqual((line["unit_price"], line["source"]), (None, "work_order"))
