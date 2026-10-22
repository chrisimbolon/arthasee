"""
Phase 21, Task 21.2 (19 Oct 2026) -- the "Buat Invoice" form's jasa lines
are suggested from the approved Estimate, since the WO no longer carries
any price (Task 21.1). See apps.invoicing.suggestions for the rules.
"""
from datetime import date
from decimal import Decimal

from apps.accounting.models import OpeningBalanceSession
from apps.authentication.models import CustomUser
from apps.estimates.models import Estimate, EstimateLineItem
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import WorkOrder, WorkOrderJobLine
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APITestCase

from ..suggestions import suggested_labor_lines


class SuggestedLaborLinesBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.owner = CustomUser.objects.create_user(
            email="owner.suggest@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        session = OpeningBalanceSession.objects.create(organization=self.org, start_date=date(2026, 9, 1))
        session.confirm_zero(confirmed_by=self.owner)
        self.customer = Customer.objects.create(organization=self.org, name="Virgil Donati")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 2215 AS",
            manufacture_year=2021, vehicle_type="Mobil", model="Toyota Avanza",
        )
        self.client.force_authenticate(user=self.owner)

    def _estimate(self, *labor):
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        for description, qty, price in labor:
            EstimateLineItem.objects.create(
                organization=self.org, estimate=estimate, kind="labor",
                description=description, quantity=Decimal(qty), unit_price=Decimal(price),
            )
        return estimate

    def _service_record_for(self, work_order):
        """Links a ServiceRecord the same way the WO master-list tests do --
        suggestions only read service_record.work_order."""
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle, service_date=date.today(),
            odometer_km=35000, issue_description="Servis",
        )
        work_order.service_record = record
        work_order.save(update_fields=["service_record"])
        return record


class ApproveRecordsTheLinkTests(SuggestedLaborLinesBase):

    def test_approve_links_each_job_line_to_its_estimate_line(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        work_order = estimate.approve(approved_by=self.owner)
        job_line = WorkOrderJobLine.objects.get(work_order=work_order)
        self.assertEqual(job_line.estimate_line_item, estimate.line_items.get())


class SuggestedLaborLinesTests(SuggestedLaborLinesBase):

    def test_estimate_price_and_quantity_are_suggested(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"), ("Spooring", "2", "75000"))
        record = self._service_record_for(estimate.approve(approved_by=self.owner))
        lines = suggested_labor_lines(record)
        self.assertEqual(
            [(l["description"], l["quantity"], l["unit_price"], l["source"]) for l in lines],
            [("Jasa Ganti Oli", Decimal("1.00"), Decimal("100000.00"), "estimate"),
             ("Spooring", Decimal("2.00"), Decimal("75000.00"), "estimate")],
        )

    def test_price_follows_the_link_even_if_the_wo_renamed_the_line(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        work_order = estimate.approve(approved_by=self.owner)
        job_line = WorkOrderJobLine.objects.get(work_order=work_order)
        job_line.description = "Ganti oli mesin + filter"
        job_line.save(update_fields=["description"])
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual(lines[0]["description"], "Ganti oli mesin + filter")
        self.assertEqual(lines[0]["unit_price"], Decimal("100000.00"))

    def test_jasa_added_on_the_wo_has_no_price(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        work_order = estimate.approve(approved_by=self.owner)
        WorkOrderJobLine.objects.create(organization=self.org, work_order=work_order, description="Kuras radiator")
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual(lines[1]["description"], "Kuras radiator")
        self.assertIsNone(lines[1]["unit_price"])
        self.assertEqual(lines[1]["source"], "work_order")

    def test_estimate_line_deleted_on_the_wo_is_not_suggested(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"), ("Spooring", "1", "75000"))
        work_order = estimate.approve(approved_by=self.owner)
        WorkOrderJobLine.objects.get(work_order=work_order, description="Spooring").delete()
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual([l["description"] for l in lines], ["Jasa Ganti Oli"])

    def test_legacy_price_text_is_read_and_stripped(self):
        """WOs approved before 16 Oct 2026: no link, price inside the text."""
        estimate = self._estimate(("Setel Rem", "2", "200000"))
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.status = "APPROVED"
        estimate.work_order = work_order
        estimate.save(update_fields=["status", "work_order"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="Setel Rem (estimasi Rp 200.000)",
        )
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual(lines[0]["description"], "Setel Rem")
        self.assertEqual(lines[0]["unit_price"], Decimal("200000.00"))
        self.assertEqual(lines[0]["quantity"], Decimal("2.00"))  # from the matching estimate line

    def test_legacy_price_text_without_a_matching_estimate_line(self):
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=work_order, description="Overhaul (estimasi Rp 1.500.000)",
        )
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual((lines[0]["unit_price"], lines[0]["quantity"]), (Decimal("1500000"), Decimal("1")))

    def test_same_description_match_for_wos_approved_16_to_19_oct(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.status = "APPROVED"
        estimate.work_order = work_order
        estimate.save(update_fields=["status", "work_order"])
        WorkOrderJobLine.objects.create(organization=self.org, work_order=work_order, description="Jasa Ganti Oli")
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual(lines[0]["unit_price"], Decimal("100000.00"))
        self.assertEqual(lines[0]["source"], "estimate")

    def test_each_estimate_line_is_used_only_once(self):
        estimate = self._estimate(("Cuci mobil", "1", "50000"))
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.status = "APPROVED"
        estimate.work_order = work_order
        estimate.save(update_fields=["status", "work_order"])
        for _ in range(2):
            WorkOrderJobLine.objects.create(organization=self.org, work_order=work_order, description="Cuci mobil")
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual([l["unit_price"] for l in lines], [Decimal("50000.00"), None])

    def test_direct_wo_without_estimate(self):
        work_order = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        WorkOrderJobLine.objects.create(organization=self.org, work_order=work_order, description="Ganti aki")
        lines = suggested_labor_lines(self._service_record_for(work_order))
        self.assertEqual([(l["description"], l["unit_price"], l["source"]) for l in lines],
                         [("Ganti aki", None, "work_order")])

    def test_service_record_without_work_order(self):
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle, service_date=date.today(),
            odometer_km=1000, issue_description="Catatan lama",
        )
        self.assertEqual(suggested_labor_lines(record), [])


class SuggestedLaborLinesAPITests(SuggestedLaborLinesBase):

    def test_endpoint_returns_strings_and_writes_nothing(self):
        from apps.invoicing.models import Invoice
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        record = self._service_record_for(estimate.approve(approved_by=self.owner))
        resp = self.client.get(f"/api/service-records/{record.id}/invoice/suggested-lines/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["labor_lines"], [{
            "description": "Jasa Ganti Oli", "quantity": "1.00",
            "unit_price": "100000.00", "source": "estimate",
        }])
        self.assertFalse(Invoice.objects.filter(service_record=record).exists())

    def test_other_organization_gets_404(self):
        estimate = self._estimate(("Jasa Ganti Oli", "1", "100000"))
        record = self._service_record_for(estimate.approve(approved_by=self.owner))
        other_org = Organization.objects.create(name="Bengkel Lain Suggest", invoice_code="BLS")
        other = CustomUser.objects.create_user(
            email="owner.othersuggest@test.id", password="pass12345!", full_name="Other",
            role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=other_org, user=other, role="owner", is_active=True)
        self.client.force_authenticate(user=other)
        resp = self.client.get(f"/api/service-records/{record.id}/invoice/suggested-lines/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
