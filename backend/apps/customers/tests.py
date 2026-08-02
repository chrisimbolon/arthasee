# =============================================================================
# === backend/apps/customers/tests.py ===
# =============================================================================
from apps.authentication.models import CustomUser
from apps.inventory.models import Part
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from apps.workorders.models import (Mechanic, WorkOrder, WorkOrderJobLine,
                                    WorkOrderStage)
from rest_framework import status
from rest_framework.test import APITestCase

from .models import TrackingLink


class CustomersAPITestBase(APITestCase):
    """
    Same real fixture shape already proven throughout this project
    (see apps.workorders.tests.WorkOrderAPITestBase) — one org, one
    owner, one customer/vehicle, force-authenticated by default.
    Public-endpoint tests deliberately do NOT authenticate — see
    PublicTrackingViewTests below, which uses its own fresh client.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.customers@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer,
            plate_number="BP 1451 AA", manufacture_year=2022,
            vehicle_type="Mobil", model="Mitsubishi Xtrada",
        )
        self.mechanic = Mechanic.objects.create(organization=self.org, name="Yoga")
        self.wo = WorkOrder.objects.create(
            organization=self.org, vehicle=self.vehicle, assigned_to=self.mechanic,
        )
        self.client.force_authenticate(user=self.owner)

    def _done_work_order_with_invoice(self, wo):
        """
        Real, full pipeline — OPEN -> IN_PROGRESS -> (one done job
        line) -> QC -> DONE -> a real Invoice — matching every one of
        this session's own confirmed rules (WorkOrder.close() requires
        QC; QC requires all job lines done; Invoice requires a real
        assigned mechanic). No shortcuts, since PublicTrackingView's
        own invoice gate depends on this chain being genuinely real,
        not faked.
        """
        wo.status = "IN_PROGRESS"
        wo.save(update_fields=["status"])
        line = WorkOrderJobLine.objects.create(
            organization=self.org, work_order=wo, description="Ganti kampas rem", is_done=True,
        )
        wo.status = "QC"
        wo.save(update_fields=["status"])
        record = wo.close(closed_by=self.owner)
        invoice = Invoice.objects.create(service_record=record)
        return invoice


class TrackingLinkModelTests(CustomersAPITestBase):

    def test_token_is_generated_automatically(self):
        link = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        self.assertTrue(link.token)
        self.assertGreaterEqual(len(link.token), 32)

    def test_two_links_get_different_tokens(self):
        first = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        second = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        self.assertNotEqual(first.token, second.token)

    def test_record_view_increments_count_and_sets_timestamp(self):
        link = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        self.assertEqual(link.view_count, 0)
        self.assertIsNone(link.last_viewed_at)

        link.record_view()
        link.refresh_from_db()
        self.assertEqual(link.view_count, 1)
        self.assertIsNotNone(link.last_viewed_at)

        link.record_view()
        link.refresh_from_db()
        self.assertEqual(link.view_count, 2)


class TrackingLinkListViewTests(CustomersAPITestBase):

    def test_can_create_a_tracking_link(self):
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/tracking-links/")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data["tracking_link"]["token"])
        self.assertFalse(resp.data["tracking_link"]["is_revoked"])

    def test_can_list_tracking_links_for_a_work_order(self):
        TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        resp = self.client.get(f"/api/work-orders/{self.wo.id}/tracking-links/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 2)

    def test_cannot_create_a_link_for_another_organizations_work_order(self):
        other_org = Organization.objects.create(name="Bengkel Lain", invoice_code="BL")
        other_customer = Customer.objects.create(organization=other_org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=other_org, customer=other_customer, plate_number="BP 9999 ZZ",
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        other_wo = WorkOrder.objects.create(organization=other_org, vehicle=other_vehicle)
        resp = self.client.post(f"/api/work-orders/{other_wo.id}/tracking-links/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(TrackingLink.objects.filter(work_order=other_wo).exists())

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(f"/api/work-orders/{self.wo.id}/tracking-links/")
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


class TrackingLinkRevokeViewTests(CustomersAPITestBase):

    def test_can_revoke_a_link(self):
        link = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        resp = self.client.post(f"/api/tracking-links/{link.id}/revoke/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        link.refresh_from_db()
        self.assertTrue(link.is_revoked)

    def test_revoked_link_stops_working_on_the_public_endpoint(self):
        link = TrackingLink.objects.create(organization=self.org, work_order=self.wo)
        self.client.post(f"/api/tracking-links/{link.id}/revoke/")

        public_client = self.client_class()  # fresh, unauthenticated client
        resp = public_client.get(f"/api/track/{link.token}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class PublicTrackingViewTests(CustomersAPITestBase):
    """
    The one deliberately unauthenticated endpoint in this whole API.
    Every test in this class uses a fresh, never-authenticated client
    — this.client (force_authenticate'd in setUp) is deliberately NOT
    used here, so these tests genuinely prove the endpoint works with
    zero session, not just that it tolerates one being present.
    """

    def setUp(self):
        super().setUp()
        self.public_client = self.client_class()
        self.link = TrackingLink.objects.create(organization=self.org, work_order=self.wo)

    def test_returns_404_for_an_unknown_token(self):
        resp = self.public_client.get("/api/track/this-token-does-not-exist/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_404_for_a_revoked_token(self):
        self.link.is_revoked = True
        self.link.save(update_fields=["is_revoked"])
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_returns_basic_work_order_info_with_no_authentication_at_all(self):
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        tracking = resp.data["tracking"]
        self.assertEqual(tracking["work_order_number"], self.wo.number)
        self.assertEqual(tracking["vehicle_plate"], "BP 1451 AA")
        self.assertEqual(tracking["vehicle_model"], "Mitsubishi Xtrada")
        self.assertEqual(tracking["mechanic_name"], "Yoga")

    def test_fetching_records_a_real_view(self):
        self.assertEqual(self.link.view_count, 0)
        self.public_client.get(f"/api/track/{self.link.token}/")
        self.link.refresh_from_db()
        self.assertEqual(self.link.view_count, 1)
        self.assertIsNotNone(self.link.last_viewed_at)

        self.public_client.get(f"/api/track/{self.link.token}/")
        self.link.refresh_from_db()
        self.assertEqual(self.link.view_count, 2)

    def test_stage_statuses_are_labeled_correctly(self):
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])
        WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Belum Dimulai", sequence=1,
        )
        in_progress = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Sedang Dikerjakan", sequence=2,
        )
        in_progress.start()
        in_progress.save()
        done = WorkOrderStage.objects.create(
            organization=self.org, work_order=self.wo, name="Sudah Selesai", sequence=3,
        )
        done.start()
        done.complete()
        done.save()

        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        stages = {s["name"]: s["status"] for s in resp.data["tracking"]["stages"]}
        self.assertEqual(stages["Belum Dimulai"], "Menunggu")
        self.assertEqual(stages["Sedang Dikerjakan"], "Sedang Berjalan")
        self.assertEqual(stages["Sudah Selesai"], "Selesai")

    def test_no_job_line_level_detail_is_exposed(self):
        """
        Chris's own explicit Fase 2 v1 scope: stage-level only, not
        job-line detail — that's Sansan's mockup's granularity, not
        what Made's signed note asked for.
        """
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, description="Ganti kampas rem depan",
        )
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        self.assertNotIn("job_lines", resp.data["tracking"])
        self.assertNotIn("Ganti kampas rem depan", str(resp.data["tracking"]))

    def test_invoice_is_excluded_while_work_order_is_not_done(self):
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        self.assertIsNone(resp.data["tracking"]["invoice"])

    def test_invoice_is_excluded_when_done_but_no_invoice_exists_yet(self):
        self.wo.status = "IN_PROGRESS"
        self.wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=self.wo, description="Ganti oli", is_done=True,
        )
        self.wo.status = "QC"
        self.wo.save(update_fields=["status"])
        self.wo.close(closed_by=self.owner)
        # Deliberately no Invoice created here — DONE alone must not
        # be enough to show invoice data.

        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        self.assertEqual(resp.data["tracking"]["status"], "Selesai")
        self.assertIsNone(resp.data["tracking"]["invoice"])

    def test_invoice_is_included_once_work_order_is_done_with_a_real_invoice(self):
        invoice = self._done_work_order_with_invoice(self.wo)
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        tracking_invoice = resp.data["tracking"]["invoice"]
        self.assertIsNotNone(tracking_invoice)
        self.assertEqual(tracking_invoice["number"], invoice.number)
        self.assertEqual(tracking_invoice["mechanic_name_snapshot"], "Yoga")

    def test_no_contract_or_termin_financial_data_is_exposed(self):
        """
        Chris's own explicit scope call: institutional clients pay via
        TerminPeriod schedules, not a flat invoice — this view has no
        business showing that, even once an invoice exists.
        """
        self._done_work_order_with_invoice(self.wo)
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        payload_str = str(resp.data["tracking"])
        self.assertNotIn("termin", payload_str.lower())
        self.assertNotIn("contract", payload_str.lower())
        self.assertNotIn("kontrak", payload_str.lower())

    def test_response_never_leaks_raw_internal_ids(self):
        """
        The real, direct proof behind PublicTrackingSerializer's own
        whitelist-only design — a public, unauthenticated endpoint
        must never expose the real internal WorkOrder/Vehicle/
        Organization UUIDs, even incidentally.
        """
        resp = self.public_client.get(f"/api/track/{self.link.token}/")
        payload_str = str(resp.data["tracking"])
        self.assertNotIn(str(self.wo.id), payload_str)
        self.assertNotIn(str(self.vehicle.id), payload_str)
        self.assertNotIn(str(self.org.id), payload_str)
