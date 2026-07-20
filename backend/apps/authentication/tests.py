# =============================================================================
# === backend/apps/authentication/tests.py ===
# =============================================================================
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import Organization, OrganizationMembership

from .models import CustomUser


class RegisterViewTests(APITestCase):
    """
    RegisterView is the actual gateway anyone new to Arthasee goes
    through first — worth testing as carefully as anything in
    apps.service, not left as "I wrote it carefully" without proof.
    """

    def _payload(self, **overrides):
        payload = {
            "email": "owner.register@test.id",
            "password": "pass12345!",
            "full_name": "Made Owner",
            "phone": "081200000000",
            "organization_name": "Arya Motor Test",
        }
        payload.update(overrides)
        return payload

    def test_register_creates_user_org_and_membership_together(self):
        resp = self.client.post("/api/auth/register/", self._payload(), format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        user = CustomUser.objects.get(email="owner.register@test.id")
        self.assertEqual(user.role, CustomUser.Role.OWNER)
        self.assertEqual(user.full_name, "Made Owner")

        org = Organization.objects.get(name="Arya Motor Test")
        membership = OrganizationMembership.objects.get(user=user, organization=org)
        self.assertEqual(membership.role, "owner")
        self.assertTrue(membership.is_active)

    def test_register_returns_usable_jwt_tokens(self):
        resp = self.client.post("/api/auth/register/", self._payload(), format="json")
        self.assertIn("access", resp.data["tokens"])
        self.assertIn("refresh", resp.data["tokens"])
        # Prove the token is actually usable, not just present in the
        # response — hit an authenticated endpoint with it directly.
        access = resp.data["tokens"]["access"]
        me_resp = self.client.get(
            "/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {access}"
        )
        self.assertEqual(me_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(me_resp.data["user"]["email"], "owner.register@test.id")

    def test_duplicate_email_rejected(self):
        self.client.post("/api/auth/register/", self._payload(), format="json")
        resp = self.client.post(
            "/api/auth/register/",
            self._payload(organization_name="A Different Shop Name"),
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # Exactly one user with this email — the second attempt must
        # not have created anything at all, partial or otherwise.
        self.assertEqual(CustomUser.objects.filter(email="owner.register@test.id").count(), 1)

    def test_missing_organization_name_creates_nothing(self):
        """
        The actual atomicity claim, proven directly: a request that
        fails validation must leave zero new rows behind — not a
        User with no Organization, not any partial state.
        """
        payload = self._payload()
        del payload["organization_name"]
        resp = self.client.post("/api/auth/register/", payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CustomUser.objects.filter(email="owner.register@test.id").exists())

    def test_password_too_short_rejected(self):
        resp = self.client.post(
            "/api/auth/register/", self._payload(password="short"), format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CustomUser.objects.filter(email="owner.register@test.id").exists())


class LoginTests(APITestCase):

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="login.test@test.id", password="pass12345!",
            full_name="Login Test User", role=CustomUser.Role.OWNER,
        )

    def test_valid_credentials_return_tokens(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "login.test@test.id", "password": "pass12345!"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)

    def test_wrong_password_rejected(self):
        resp = self.client.post(
            "/api/auth/login/",
            {"email": "login.test@test.id", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class MeViewTests(APITestCase):

    def test_unauthenticated_request_rejected(self):
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_request_returns_own_user(self):
        user = CustomUser.objects.create_user(
            email="me.test@test.id", password="pass12345!",
            full_name="Me Test User", role=CustomUser.Role.OWNER,
        )
        self.client.force_authenticate(user=user)
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["user"]["email"], "me.test@test.id")
