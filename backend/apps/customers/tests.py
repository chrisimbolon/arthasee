# =============================================================================
# === backend/apps/customers/tests.py ===
# =============================================================================
from datetime import timedelta
from unittest.mock import patch

from apps.authentication.models import CustomUser
from apps.inventory.models import Part
from apps.invoicing.models import Invoice
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from apps.workorders.models import (Mechanic, WorkOrder, WorkOrderJobLine,
                                    WorkOrderStage)
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .auth import generate_customer_access_token
from .models import MagicLinkToken, TrackingLink


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


def _customer_auth_header(customer):
    """Shared by every Fase 2.5 test class below that needs a real,
    valid customer session — mirrors the exact header shape
    CustomerJWTAuthentication expects (see auth.py)."""
    token = generate_customer_access_token(customer)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class MagicLinkTokenModelTests(CustomersAPITestBase):

    def setUp(self):
        super().setUp()
        self.customer.email = "brian@test.id"
        self.customer.save(update_fields=["email"])

    def test_token_is_generated_automatically(self):
        link = MagicLinkToken.objects.create(
            organization=self.org, customer=self.customer,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.assertTrue(link.token)
        self.assertGreaterEqual(len(link.token), 32)

    def test_is_valid_true_for_a_fresh_unused_token(self):
        link = MagicLinkToken.objects.create(
            organization=self.org, customer=self.customer,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        self.assertTrue(link.is_valid)

    def test_is_valid_false_once_marked_used(self):
        link = MagicLinkToken.objects.create(
            organization=self.org, customer=self.customer,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        link.mark_used()
        self.assertFalse(link.is_valid)
        self.assertIsNotNone(link.used_at)

    def test_is_valid_false_once_expired(self):
        link = MagicLinkToken.objects.create(
            organization=self.org, customer=self.customer,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(link.is_valid)


class CustomerMagicLinkRequestViewTests(CustomersAPITestBase):
    """
    Public client throughout — requesting a magic link is, by
    definition, something a not-yet-logged-in customer does.
    """

    def setUp(self):
        super().setUp()
        self.customer.email = "brian@test.id"
        self.customer.save(update_fields=["email"])
        self.public_client = self.client_class()

    def test_creates_a_real_token_when_email_matches_a_customer(self):
        self.assertEqual(MagicLinkToken.objects.count(), 0)
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(MagicLinkToken.objects.count(), 1)
        self.assertEqual(MagicLinkToken.objects.first().customer, self.customer)

    def test_email_matching_is_case_insensitive(self):
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "BRIAN@TEST.ID"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(MagicLinkToken.objects.count(), 1)

    def test_no_token_created_when_email_matches_nobody(self):
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "nobody@test.id"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(MagicLinkToken.objects.count(), 0)

    def test_response_is_identical_whether_or_not_the_email_exists(self):
        """
        Real security property, not incidental — a public endpoint
        must never let an attacker learn whether a given email is a
        real customer just by watching the response shape.
        """
        matched = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        unmatched = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "nobody@test.id"}, format="json",
        )
        self.assertEqual(matched.status_code, unmatched.status_code)
        self.assertEqual(matched.data["message"], unmatched.data["message"])

    def test_missing_email_is_rejected(self):
        resp = self.public_client.post("/api/customer-auth/magic-link/", {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(DEBUG=True)
    def test_dev_token_included_in_response_when_debug_is_true(self):
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        self.assertIn("dev_token", resp.data)
        self.assertEqual(resp.data["dev_token"], MagicLinkToken.objects.first().token)

    @override_settings(DEBUG=False)
    def test_dev_token_never_included_when_debug_is_false(self):
        """
        The one test that actually matters most in this class — a
        magic-link token must never appear in an API response once
        this is treated as production-shaped, since that would let
        anyone who can see the response log in as someone else.
        """
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        self.assertNotIn("dev_token", resp.data)


class CustomerMagicLinkVerifyViewTests(CustomersAPITestBase):

    def setUp(self):
        super().setUp()
        self.customer.email = "brian@test.id"
        self.customer.save(update_fields=["email"])
        self.public_client = self.client_class()
        self.link = MagicLinkToken.objects.create(
            organization=self.org, customer=self.customer,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

    def test_valid_token_returns_a_real_access_token_and_session_info(self):
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        session = resp.data["session"]
        self.assertTrue(session["access"])
        self.assertEqual(session["name"], "Brian Sira")
        self.assertEqual(session["email"], "brian@test.id")

    def test_verifying_marks_the_token_used(self):
        self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        self.link.refresh_from_db()
        self.assertIsNotNone(self.link.used_at)

    def test_a_used_token_cannot_be_redeemed_twice(self):
        self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        second = self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_expired_token_is_rejected(self):
        self.link.expires_at = timezone.now() - timedelta(minutes=1)
        self.link.save(update_fields=["expires_at"])
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_an_unknown_token_is_rejected(self):
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": "this-token-does-not-exist"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_returned_access_token_actually_works_on_a_protected_endpoint(self):
        """
        The real, end-to-end proof — not just that verify() returns
        something that looks like a token, but that the whole chain
        (magic link -> access token -> CustomerJWTAuthentication)
        genuinely holds together.
        """
        verify_resp = self.public_client.post(
            "/api/customer-auth/magic-link/verify/", {"token": self.link.token}, format="json",
        )
        access = verify_resp.data["session"]["access"]
        resp = self.public_client.get(
            "/api/customer/work-orders/", **{"HTTP_AUTHORIZATION": f"Bearer {access}"},
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class CustomerWorkOrdersListViewTests(CustomersAPITestBase):

    def setUp(self):
        super().setUp()
        self.public_client = self.client_class()
        self.wo_active = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self.wo_done = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        self._ready_to_close(self.wo_done)
        self.wo_done.close(closed_by=self.owner)

    def _ready_to_close(self, wo):
        # Same shape as apps.workorders.tests' own helper — this file
        # has no shared base with that one, so reimplemented locally
        # rather than importing across apps' test modules.
        wo.status = "IN_PROGRESS"
        wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=wo, description="(qc placeholder)", is_done=True,
        )
        wo.status = "QC"
        wo.save(update_fields=["status"])
        return wo

    def test_requires_a_valid_customer_token(self):
        resp = self.public_client.get("/api/customer/work-orders/")
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_a_customuser_token_does_not_grant_access(self):
        """
        Real proof of the "complete separation" requirement — an
        internal CustomUser session (even a real, valid one) must
        never be usable to authenticate as a customer.
        """
        self.public_client.force_authenticate(user=self.owner)
        resp = self.public_client.get("/api/customer/work-orders/")
        self.assertIn(resp.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_returns_active_and_history_split_correctly(self):
        resp = self.public_client.get("/api/customer/work-orders/", **_customer_auth_header(self.customer))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        active_numbers = [wo["work_order_number"] for wo in resp.data["active"]]
        history_numbers = [wo["work_order_number"] for wo in resp.data["history"]]
        self.assertIn(self.wo_active.number, active_numbers)
        self.assertIn(self.wo_done.number, history_numbers)
        self.assertNotIn(self.wo_done.number, active_numbers)
        self.assertNotIn(self.wo_active.number, history_numbers)

    def test_only_returns_this_customers_own_work_orders(self):
        other_customer = Customer.objects.create(organization=self.org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=self.org, customer=other_customer, plate_number="BP 9999 ZZ",
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        WorkOrder.objects.create(organization=self.org, vehicle=other_vehicle)

        resp = self.public_client.get("/api/customer/work-orders/", **_customer_auth_header(self.customer))
        all_numbers = [wo["work_order_number"] for wo in resp.data["active"] + resp.data["history"]]
        # Three of OUR OWN, not two — the real bug was in this
        # assertion, not the view. CustomersAPITestBase's own setUp()
        # already creates self.wo (a third WorkOrder on the same
        # vehicle, for TrackingLink/PublicTracking tests elsewhere in
        # this file), in addition to this class's own wo_active/
        # wo_done. My first draft here forgot that inherited fixture
        # entirely — caught by a real test failure, traced by
        # actually re-reading the base class instead of trusting
        # memory a second time.
        self.assertEqual(len(all_numbers), 3)
        self.assertIn(self.wo.number, all_numbers)
        self.assertIn(self.wo_active.number, all_numbers)
        self.assertIn(self.wo_done.number, all_numbers)


class CustomerWorkOrderDetailViewTests(CustomersAPITestBase):

    def setUp(self):
        super().setUp()
        self.public_client = self.client_class()
        self.wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)

    def _done_work_order_with_invoice(self, wo):
        wo.status = "IN_PROGRESS"
        wo.save(update_fields=["status"])
        WorkOrderJobLine.objects.create(
            organization=self.org, work_order=wo, description="Ganti oli", is_done=True,
        )
        wo.status = "QC"
        wo.save(update_fields=["status"])
        wo.assigned_to = self.mechanic
        wo.save(update_fields=["assigned_to"])
        record = wo.close(closed_by=self.owner)
        return Invoice.objects.create(service_record=record)

    def test_can_fetch_own_work_order_detail(self):
        resp = self.public_client.get(
            f"/api/customer/work-orders/{self.wo.id}/", **_customer_auth_header(self.customer),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["tracking"]["work_order_number"], self.wo.number)

    def test_cannot_fetch_another_customers_work_order(self):
        """
        The real ownership check — a logged-in customer must only
        ever reach a WorkOrder for one of THEIR OWN vehicles, not any
        id they happen to guess or construct.
        """
        other_customer = Customer.objects.create(organization=self.org, name="Pelanggan Lain")
        other_vehicle = Vehicle.objects.create(
            organization=self.org, customer=other_customer, plate_number="BP 9999 ZZ",
            vehicle_type="Mobil", model="Test", manufacture_year=2020,
        )
        other_wo = WorkOrder.objects.create(organization=self.org, vehicle=other_vehicle)

        resp = self.public_client.get(
            f"/api/customer/work-orders/{other_wo.id}/", **_customer_auth_header(self.customer),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_invoice_included_once_done_with_a_real_invoice(self):
        invoice = self._done_work_order_with_invoice(self.wo)
        resp = self.public_client.get(
            f"/api/customer/work-orders/{self.wo.id}/", **_customer_auth_header(self.customer),
        )
        self.assertEqual(resp.data["tracking"]["invoice"]["number"], invoice.number)

    def test_invoice_excluded_while_still_in_progress(self):
        resp = self.public_client.get(
            f"/api/customer/work-orders/{self.wo.id}/", **_customer_auth_header(self.customer),
        )
        self.assertIsNone(resp.data["tracking"]["invoice"])


class MagicLinkEmailTests(CustomersAPITestBase):
    """
    Tests for email.py directly, not through the view — real
    Resend calls are always mocked here (patch("resend.Emails.send")),
    never a genuine network call, matching the same discipline as
    every other test in this project. NOTE: these tests require the
    `resend` package to actually be installed (import resend happens
    inside send_magic_link_email itself, only once an API key is
    configured) — if it isn't yet, the tests using
    @override_settings(RESEND_API_KEY=...) will fail on that import,
    not on anything this test file itself gets wrong.
    """

    def setUp(self):
        super().setUp()
        self.customer.email = "brian@test.id"
        self.customer.save(update_fields=["email"])

    def test_returns_false_when_api_key_not_configured(self):
        """
        The real, current state as of 3 Aug — no RESEND_API_KEY set
        up yet. Must fail soft, not raise.
        """
        from .email import send_magic_link_email
        result = send_magic_link_email(self.customer, "some-token")
        self.assertFalse(result)

    @override_settings(RESEND_API_KEY="test_key_123")
    @patch("resend.Emails.send")
    def test_sends_and_returns_true_when_configured_and_resend_succeeds(self, mock_send):
        from .email import send_magic_link_email
        result = send_magic_link_email(self.customer, "some-token")
        self.assertTrue(result)
        mock_send.assert_called_once()

    @override_settings(RESEND_API_KEY="test_key_123")
    @patch("resend.Emails.send")
    def test_returns_false_when_resend_raises(self, mock_send):
        """
        A real provider-side failure (bad key, outage, rate limit)
        must never bubble up into a 500 on the request endpoint —
        the whole reason this function catches broadly rather than
        letting an exception propagate.
        """
        mock_send.side_effect = Exception("Resend API error")
        from .email import send_magic_link_email
        result = send_magic_link_email(self.customer, "some-token")
        self.assertFalse(result)

    @override_settings(RESEND_API_KEY="test_key_123", FRONTEND_BASE_URL="https://arthasee.com")
    @patch("resend.Emails.send")
    def test_email_includes_the_real_magic_link_url_and_recipient(self, mock_send):
        from .email import send_magic_link_email
        send_magic_link_email(self.customer, "abc123token")
        call_args = mock_send.call_args[0][0]
        self.assertEqual(call_args["to"], ["brian@test.id"])
        self.assertIn("https://arthasee.com/customer/verify?token=abc123token", call_args["html"])
        self.assertIn(self.org.name, call_args["subject"])


class CustomerMagicLinkRequestViewEmailWiringTests(CustomersAPITestBase):
    """
    Proves the view actually calls send_magic_link_email — separate
    from CustomerMagicLinkRequestViewTests above (which predates the
    real Resend wiring and deliberately doesn't mock anything, relying
    on RESEND_API_KEY being unset in test settings so the real
    function fails soft on its own). These tests mock at the views.py
    import site specifically (apps.customers.views.send_magic_link_email,
    not apps.customers.email.send_magic_link_email) — patching a
    function only affects the name actually called from, and views.py
    holds its own bound reference via `from .email import
    send_magic_link_email`.
    """

    def setUp(self):
        super().setUp()
        self.customer.email = "brian@test.id"
        self.customer.save(update_fields=["email"])
        self.public_client = self.client_class()

    @patch("apps.customers.views.send_magic_link_email")
    def test_view_calls_send_magic_link_email_when_a_customer_matches(self, mock_send):
        mock_send.return_value = True
        self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        mock_send.assert_called_once()
        called_customer = mock_send.call_args[0][0]
        self.assertEqual(called_customer.id, self.customer.id)

    @patch("apps.customers.views.send_magic_link_email")
    def test_view_does_not_call_send_when_no_customer_matches(self, mock_send):
        self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "nobody@test.id"}, format="json",
        )
        mock_send.assert_not_called()

    @override_settings(DEBUG=True)
    @patch("apps.customers.views.send_magic_link_email")
    def test_dev_token_self_eliminates_once_a_real_send_succeeds(self, mock_send):
        """
        The actual point of the redesigned dev_token logic: once a
        real send genuinely works, dev_token must NOT appear in the
        response even in DEBUG — no manual cleanup needed once Resend
        is properly configured.
        """
        mock_send.return_value = True
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        self.assertNotIn("dev_token", resp.data)

    @override_settings(DEBUG=True)
    @patch("apps.customers.views.send_magic_link_email")
    def test_dev_token_still_present_when_send_fails_in_debug(self, mock_send):
        mock_send.return_value = False
        resp = self.public_client.post(
            "/api/customer-auth/magic-link/", {"email": "brian@test.id"}, format="json",
        )
        self.assertIn("dev_token", resp.data)
