# =============================================================================
# === backend/apps/organizations/tests.py ===
# =============================================================================
from rest_framework import status
from rest_framework.test import APITestCase

from apps.authentication.models import CustomUser

from .models import Organization, OrganizationMembership


class MyOrganizationViewTests(APITestCase):

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/organizations/mine/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_with_active_membership_sees_their_org(self):
        org = Organization.objects.create(name="Arya Motor Org Test")
        user = CustomUser.objects.create_user(
            email="orgmine.test@test.id", password="pass12345!",
            full_name="Org Mine User", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role="owner", is_active=True,
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/organizations/mine/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["organization"]["name"], "Arya Motor Org Test")
        self.assertEqual(resp.data["role"], "owner")

    def test_user_with_no_membership_gets_friendly_404(self):
        user = CustomUser.objects.create_user(
            email="orphan.test@test.id", password="pass12345!",
            full_name="Orphan User", role=CustomUser.Role.OWNER,
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/organizations/mine/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(resp.data["success"])

    def test_inactive_membership_is_not_returned(self):
        """A membership that's been deactivated shouldn't silently
        still grant access to its organization."""
        org = Organization.objects.create(name="Bengkel Nonaktif")
        user = CustomUser.objects.create_user(
            email="inactive.test@test.id", password="pass12345!",
            full_name="Inactive Member", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role="owner", is_active=False,
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/organizations/mine/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
