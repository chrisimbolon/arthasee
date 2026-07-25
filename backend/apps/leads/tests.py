# =============================================================================
# === backend/apps/leads/tests.py ===
# =============================================================================
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership

from .models import RejectedQuote


class LeadsAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.leads@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=self.owner)


class RejectedQuoteTests(LeadsAPITestBase):

    def test_create_rejected_quote(self):
        resp = self.client.post(
            "/api/leads/rejected-quotes/",
            {
                "name": "Budi Baru", "phone": "081234567890",
                "vehicle_description": "Toyota Avanza putih, sekitar 2018",
                "quoted_description": "Ganti kampas rem dan rotor",
                "quoted_amount": "1500000",
                "reason": "TOO_EXPENSIVE",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["rejected_quote"]["follow_up_status"], "PENDING")
        self.assertEqual(resp.data["rejected_quote"]["created_by_name"], "Made Owner")

    def test_defaults_to_pending_follow_up_status(self):
        quote = RejectedQuote.objects.create(organization=self.org, name="x")
        self.assertEqual(quote.follow_up_status, "PENDING")

    def test_filter_by_follow_up_status_is_the_call_list(self):
        RejectedQuote.objects.create(organization=self.org, name="Pending Satu", follow_up_status="PENDING")
        RejectedQuote.objects.create(organization=self.org, name="Sudah Dihubungi", follow_up_status="CONTACTED")

        resp = self.client.get("/api/leads/rejected-quotes/?follow_up_status=PENDING")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Pending Satu")

    def test_filter_by_reason(self):
        RejectedQuote.objects.create(organization=self.org, name="A", reason="TOO_EXPENSIVE")
        RejectedQuote.objects.create(organization=self.org, name="B", reason="POSTPONED")

        resp = self.client.get("/api/leads/rejected-quotes/?reason=TOO_EXPENSIVE")
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "A")

    def test_record_is_freely_editable_unlike_service_record_or_invoice(self):
        """
        Deliberately the opposite discipline from ServiceRecord/
        Invoice — this is a live working record, not a frozen
        historical one, so editing it after creation must succeed.
        """
        quote = RejectedQuote.objects.create(organization=self.org, name="Awal", phone="0800")
        resp = self.client.put(
            f"/api/leads/rejected-quotes/{quote.id}/",
            {"name": "Nama Diperbaiki", "follow_up_status": "CONTACTED", "notes": "Sudah ditelepon, mikir-mikir dulu."},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        quote.refresh_from_db()
        self.assertEqual(quote.name, "Nama Diperbaiki")
        self.assertEqual(quote.follow_up_status, "CONTACTED")

    def test_can_mark_converted_when_customer_comes_back(self):
        quote = RejectedQuote.objects.create(organization=self.org, name="x", follow_up_status="CONTACTED")
        resp = self.client.put(
            f"/api/leads/rejected-quotes/{quote.id}/",
            {"follow_up_status": "CONVERTED"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["rejected_quote"]["follow_up_status"], "CONVERTED")

    def test_delete_is_allowed_no_protect(self):
        """No PROTECT here — nothing else in the domain references a
        RejectedQuote, since Made confirmed manual conversion with no
        auto-linking to Customer/Vehicle/WorkOrder."""
        quote = RejectedQuote.objects.create(organization=self.org, name="Hapus Saya")
        resp = self.client.delete(f"/api/leads/rejected-quotes/{quote.id}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(RejectedQuote.objects.filter(id=quote.id).exists())

    def test_quoted_amount_is_optional(self):
        resp = self.client.post("/api/leads/rejected-quotes/", {"name": "Tanpa Harga"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data["rejected_quote"]["quoted_amount"])


class LeadsTenantIsolationTests(LeadsAPITestBase):

    def setUp(self):
        super().setUp()
        self.quote = RejectedQuote.objects.create(organization=self.org, name="Org A Lead")
        self.other_org = Organization.objects.create(name="Bengkel Lain Leads", invoice_code="BL")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.otherleads@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_see_org_a_leads(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get("/api/leads/rejected-quotes/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_retrieve_org_a_lead_detail(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/leads/rejected-quotes/{self.quote.id}/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_org_b_cannot_edit_org_a_lead(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.put(
            f"/api/leads/rejected-quotes/{self.quote.id}/",
            {"name": "Diretas"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
