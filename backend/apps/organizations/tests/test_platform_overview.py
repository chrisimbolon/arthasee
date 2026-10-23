"""
Phase 22 (24 Oct 2026) — the super admin's platform overview
(GET /api/platform/overview/). Read-only, super admin only, counts and
account totals only (no customer data). See platform_health.py.
"""
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

from apps.accounting.models import OpeningBalanceSession
from apps.authentication.models import CustomUser
from apps.core.models import Outbox
from apps.inventory.models import Part
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from apps.workorders.models import Mechanic, WorkOrder
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

URL = "/api/platform/overview/"


class PlatformOverviewTests(APITestCase):

    def _healthy_shop(self, name, code, owner_email):
        org = Organization.objects.create(name=name, invoice_code=code, onboarding_completed=True)
        call_command("seed_coa", organization=str(org.id), verbosity=0)
        owner = CustomUser.objects.create_user(
            email=owner_email, password="pass12345!", full_name=f"Owner {code}", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=org, user=owner, role="owner", is_active=True)
        OpeningBalanceSession.objects.create(organization=org, start_date=date(2026, 9, 1)).confirm_zero(confirmed_by=owner)
        return org, owner

    def setUp(self):
        self.org, self.owner = self._healthy_shop("Bengkel Satu", "BS", "owner.platform@test.id")
        self.admin = CustomUser.objects.create_superuser(
            email="admin.platform@test.id", password="pass12345!", full_name="Platform Admin",
        )
        self.customer = Customer.objects.create(organization=self.org, name="Brian Sira")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 2219 AB",
            manufacture_year=2022, vehicle_type="Mobil", model="Honda Brio",
        )

    def _get(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(URL)

    def _shop(self, resp, org):
        return next(s for s in resp.data["shops"] if str(s["id"]) == str(org.id))

    # ── access ──
    def test_logged_out_gets_401(self):
        self.assertEqual(self.client.get(URL).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_shop_owner_gets_403(self):
        self.assertEqual(self._get(self.owner).status_code, status.HTTP_403_FORBIDDEN)

    def test_read_only(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.post(URL, {}).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_create_superuser_is_a_super_admin(self):
        self.assertEqual(self.admin.role, "super_admin")

    # ── health ──
    def test_healthy_shop_is_green(self):
        resp = self._get(self.admin)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        shop = self._shop(resp, self.org)
        self.assertEqual(shop["status"], "green", shop["reasons"])
        self.assertTrue(shop["books"]["trial_balance_balanced"])
        self.assertEqual(shop["logins"], 1)
        self.assertEqual(resp.data["totals"]["shops"], 1)

    def test_inventory_gap_is_red(self):
        # Stock typed in without a posting: 5 x 1.000 in the subledger, 0 in 1301.
        Part.objects.create(organization=self.org, name="Busi", unit="pcs",
                            unit_price=Decimal("90000"), cost_price=Decimal("1000"), current_stock=Decimal("5"))
        shop = self._shop(self._get(self.admin), self.org)
        self.assertEqual(shop["status"], "red")
        inv = next(c for c in shop["books"]["control_accounts"] if c["account_code"] == "1301")
        self.assertFalse(inv["is_reconciled"])
        self.assertEqual(Decimal(str(inv["difference"])), Decimal("-5000"))
        self.assertTrue(any("1301" in r for r in shop["reasons"]))

    def test_failed_event_is_red_with_its_error(self):
        Outbox.objects.create(organization=self.org, event_id=uuid.uuid4(), event_type="InvoiceIssued",
                              payload={}, occurred_at=timezone.now(), status=Outbox.Status.FAILED,
                              attempts=1, last_error="No Account with code='4001'")
        shop = self._shop(self._get(self.admin), self.org)
        self.assertEqual(shop["status"], "red")
        self.assertEqual(shop["events"]["failed"], 1)
        self.assertEqual(shop["events"]["last_failure"]["event_type"], "InvoiceIssued")
        self.assertIn("4001", shop["events"]["last_failure"]["error"])

    def test_stuck_pending_event_is_amber(self):
        row = Outbox.objects.create(organization=self.org, event_id=uuid.uuid4(), event_type="PartConsumed",
                                    payload={}, occurred_at=timezone.now(), status=Outbox.Status.PENDING)
        Outbox.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=20))
        Outbox.objects.create(organization=self.org, event_id=uuid.uuid4(), event_type="PartConsumed",
                              payload={}, occurred_at=timezone.now(), status=Outbox.Status.PENDING)  # fresh: not stuck
        shop = self._shop(self._get(self.admin), self.org)
        self.assertEqual(shop["status"], "amber")
        self.assertEqual(shop["events"]["stuck_pending"], 1)

    def test_unfinished_onboarding_is_amber(self):
        Organization.objects.filter(pk=self.org.pk).update(onboarding_completed=False)
        self.assertEqual(self._shop(self._get(self.admin), self.org)["status"], "amber")

    def test_brand_new_shop_without_opening_balance_shows_the_block(self):
        bare = Organization.objects.create(name="Bengkel Baru", invoice_code="BB", onboarding_completed=True)
        call_command("seed_coa", organization=str(bare.id), verbosity=0)
        shop = self._shop(self._get(self.admin), bare)
        self.assertEqual(shop["status"], "amber")
        self.assertIn("OPENING_BALANCE_NOT_RESOLVED", shop["readiness"]["blocks"])

    def test_problems_sort_first(self):
        other, _ = self._healthy_shop("Bengkel Dua", "BD", "owner.dua@test.id")
        Part.objects.create(organization=other, name="Oli", unit="liter",
                            unit_price=Decimal("1"), cost_price=Decimal("1"), current_stock=Decimal("1"))
        resp = self._get(self.admin)
        self.assertEqual(str(resp.data["shops"][0]["id"]), str(other.id))
        self.assertEqual(resp.data["totals"]["red"], 1)

    # ── activity is per shop ──
    def test_activity_counts_only_that_shops_work_orders(self):
        other, _ = self._healthy_shop("Bengkel Dua", "BD", "owner.dua@test.id")
        mechanic = Mechanic.objects.create(organization=self.org, name="Alex")
        WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, assigned_to=mechanic)
        resp = self._get(self.admin)
        mine, theirs = self._shop(resp, self.org), self._shop(resp, other)
        self.assertEqual(mine["activity"]["work_orders"]["last_7_days"], 1)
        self.assertIsNotNone(mine["activity"]["last_activity_at"])
        self.assertEqual(theirs["activity"]["work_orders"]["last_30_days"], 0)
        self.assertIsNone(theirs["activity"]["last_activity_at"])
        self.assertEqual(resp.data["totals"]["active_last_7_days"], 1)

    # ── privacy ──
    def test_no_customer_data_in_the_response(self):
        body = json.dumps(self._get(self.admin).data, default=str)
        for secret in ("Brian Sira", "BP 2219 AB", "Honda Brio"):
            self.assertNotIn(secret, body)
