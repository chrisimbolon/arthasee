# =============================================================================
# === backend/apps/organizations/tests.py ===
# =============================================================================
from datetime import date

from apps.accounting.models import (Account, AccountingPeriod,
                                    OpeningBalanceSession)
from apps.accounting.services.readiness import check_organization_readiness
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Organization, OrganizationMembership
from .serializers import OrganizationSettingsUpdateSerializer


class OrganizationInvoiceCodeGenerationTests(SimpleTestCase):
    """
    Chris's own explicit call, 5 Aug: registration stays completely
    frictionless — invoice_code never appears on the signup form.
    Direct, DB-free unit tests against the pure algorithm itself —
    _generate_invoice_code() doesn't touch the database, so
    SimpleTestCase is enough, same discipline as
    TerbilangRupiahTests in apps.invoicing.
    """

    def test_matches_arya_motors_own_real_code(self):
        """The actual real-world precedent this algorithm was
        designed against — not a coincidence, the whole reason this
        specific rule (strip CV/PT/UD, then initial) was chosen."""
        org = Organization(name="CV. Arya Motor")
        self.assertEqual(org._generate_invoice_code(), "AM")

    def test_strips_legal_prefixes_case_insensitively(self):
        org = Organization(name="cv jaya motor")
        self.assertEqual(org._generate_invoice_code(), "JM")

    def test_does_not_strip_generic_descriptive_words(self):
        """"Bengkel" is not a real Indonesian legal-entity type
        (unlike CV/PT/UD) — a shop starting with it should keep that
        initial, not have it silently stripped."""
        org = Organization(name="Bengkel Makmur Jaya")
        self.assertEqual(org._generate_invoice_code(), "BMJ")

    def test_single_word_name_uses_first_letters_not_one_letter(self):
        org = Organization(name="Arthasee")
        code = org._generate_invoice_code()
        self.assertEqual(code, "ART")
        self.assertGreater(len(code), 1)

    def test_never_exceeds_the_fields_own_max_length(self):
        org = Organization(name="Perseroan Terbatas Sangat Panjang Sekali Namanya Ini")
        self.assertLessEqual(len(org._generate_invoice_code()), 10)

    def test_falls_back_to_org_when_name_has_no_real_letters(self):
        org = Organization(name="123")
        self.assertEqual(org._generate_invoice_code(), "ORG")


class OrganizationSaveAutoPopulatesInvoiceCodeTests(APITestCase):
    """
    Real DB-backed tests — proving save() itself wires the generator
    in correctly: fires on create, never overwrites an explicitly-set
    or owner-customized code, and only ever fires once.
    """

    def test_creating_an_organization_auto_populates_invoice_code(self):
        org = Organization.objects.create(name="CV. Arya Motor")
        self.assertEqual(org.invoice_code, "AM")

    def test_an_explicitly_provided_code_is_never_overwritten(self):
        org = Organization.objects.create(name="CV. Arya Motor", invoice_code="CUSTOM")
        self.assertEqual(org.invoice_code, "CUSTOM")

    def test_updating_the_name_later_never_regenerates_the_code(self):
        """
        The real point of only firing on self._state.adding — an
        owner who customizes their code in Settings, then later edits
        their shop's display name for an unrelated reason, must never
        have their real, deliberate customization silently
        overwritten by this fallback logic running again.
        """
        org = Organization.objects.create(name="CV. Arya Motor")
        original_code = org.invoice_code
        org.invoice_code = "MYCODE"
        org.name = "CV. Arya Motor Jaya"
        org.save()
        org.refresh_from_db()
        self.assertEqual(org.invoice_code, "MYCODE")
        self.assertNotEqual(org.invoice_code, original_code)


class OrganizationSettingsUpdateSerializerTests(SimpleTestCase):

    def test_rejects_invalid_characters(self):
        serializer = OrganizationSettingsUpdateSerializer(data={"invoice_code": "A-M!"}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("invoice_code", serializer.errors)

    def test_uppercases_and_strips_whitespace(self):
        # partial=True — matches exactly how the real view calls this
        # serializer (MyOrganizationView.patch()). Without it,
        # ModelSerializer correctly demands every model field
        # (including `name`, unrelated to what this test actually
        # checks), which is what caused a real test failure here —
        # caught live via a real test run, not assumed correct.
        serializer = OrganizationSettingsUpdateSerializer(data={"invoice_code": " am "}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["invoice_code"], "AM")

    def test_blank_is_a_real_allowed_value(self):
        """An owner deliberately clearing the field is a real,
        allowed choice — falls back to the same hard block
        Invoice.save() already enforces for a genuinely unset code,
        not a new failure mode this serializer introduces."""
        serializer = OrganizationSettingsUpdateSerializer(data={"invoice_code": ""}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)


class MyOrganizationSettingsUpdateAPITests(APITestCase):
    """Real HTTP-level coverage for PATCH /api/organizations/mine/ —
    the actual endpoint a real Organization Settings page hits."""

    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor")
        self.owner = CustomUser.objects.create_user(
            email="owner.orgsettings@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.staff = CustomUser.objects.create_user(
            email="staff.orgsettings@test.id", password="pass12345!",
            full_name="SA Staff",
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.staff, role="member", is_active=True,
        )

    def test_owner_can_customize_the_auto_generated_code(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch("/api/organizations/mine/", {"invoice_code": "ARYA"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["organization"]["invoice_code"], "ARYA")
        self.org.refresh_from_db()
        self.assertEqual(self.org.invoice_code, "ARYA")

    def test_non_owner_staff_cannot_change_settings(self):
        """Real role check, not just authentication — a staff member
        with a genuine, active membership must still be blocked from
        shop-wide settings like the invoice prefix."""
        self.client.force_authenticate(user=self.staff)
        resp = self.client.patch("/api/organizations/mine/", {"invoice_code": "HACK"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.org.refresh_from_db()
        self.assertNotEqual(self.org.invoice_code, "HACK")

    def test_cannot_self_edit_plan_or_is_active_through_this_endpoint(self):
        """The actual security boundary this serializer exists to
        enforce — plan/is_active are billing and account-status
        concerns, never self-service through "customize my invoice
        code.\""""
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch(
            "/api/organizations/mine/", {"plan": "enterprise", "is_active": False}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.org.refresh_from_db()
        self.assertEqual(self.org.plan, "free")
        self.assertTrue(self.org.is_active)

    def test_invalid_characters_rejected_via_the_real_endpoint(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch("/api/organizations/mine/", {"invoice_code": "A M!"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_can_update_shop_name_without_touching_the_code(self):
        original_code = self.org.invoice_code
        self.client.force_authenticate(user=self.owner)
        resp = self.client.patch("/api/organizations/mine/", {"name": "CV. Arya Motor Jaya"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "CV. Arya Motor Jaya")
        self.assertEqual(self.org.invoice_code, original_code)

    def test_get_now_includes_invoice_code(self):
        """GET was silently omitting invoice_code entirely before
        this — a real gap for any settings page that needs to display
        the current value."""
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get("/api/organizations/mine/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("invoice_code", resp.data["organization"])


class OrganizationOnboardingCompleteAPITests(APITestCase):
    """
    3 Sep 2026 — real, fresh coverage for the REDESIGNED complete-
    onboarding endpoint (no prior tests existed for the old
    contract). No payload anymore — Step 1's own data is expected to
    already be saved via MyOrganizationView.patch() before this is
    ever called; this endpoint's only real job is the final flag
    flip, guarded by a server-side check that Step 1 genuinely
    happened first.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor")
        self.owner = CustomUser.objects.create_user(
            email="owner.onboardcomplete@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.staff = CustomUser.objects.create_user(
            email="staff.onboardcomplete@test.id", password="pass12345!",
            full_name="SA Staff",
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.staff, role="member", is_active=True,
        )
        self.client.force_authenticate(user=self.owner)

    def _complete_step_one(self):
        """
        Real Step 1 — via the plain, already-proven PATCH path, not
        the old complete-onboarding contract. Deliberately does NOT
        assert onboarding_completed here — that is exactly the real
        behavior change this whole redesign exists to prove: Step 1
        alone must never flip the flag.
        """
        return self.client.patch("/api/organizations/mine/", {
            "phone": "0812-3456-7890", "address": "Jl. Merdeka No. 1", "invoice_code": "AM",
        }, format="json")

    def test_step_one_alone_does_not_complete_onboarding(self):
        """
        THE core regression test for the whole redesign — the actual
        gap found live during the architecture review. Before this
        fix, a single call did both jobs; now Step 1 must leave
        onboarding_completed False, so a mid-Step-2 refresh has
        something real to resume from.
        """
        self._complete_step_one()
        self.org.refresh_from_db()
        self.assertFalse(self.org.onboarding_completed)

    def test_complete_onboarding_requires_no_payload(self):
        self._complete_step_one()
        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["organization"]["onboarding_completed"])
        self.org.refresh_from_db()
        self.assertTrue(self.org.onboarding_completed)

    def test_rejected_when_step_one_data_is_missing(self):
        """
        The real server-side guard — a bare call with no prior
        profile data on record must never silently complete
        onboarding for a shop with nothing actually saved.
        """
        # self.org has no phone/address set at all — Organization.
        # objects.create(name=...) in setUp() never touched them.
        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.org.refresh_from_db()
        self.assertFalse(self.org.onboarding_completed)

    def test_non_owner_cannot_complete_onboarding(self):
        self._complete_step_one()
        self.client.force_authenticate(user=self.staff)
        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.org.refresh_from_db()
        self.assertFalse(self.org.onboarding_completed)

    def test_no_membership_returns_404(self):
        outsider = CustomUser.objects.create_user(
            email="outsider.onboardcomplete@test.id", password="pass12345!",
            full_name="No Org",
        )
        self.client.force_authenticate(user=outsider)
        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_callable_again_after_already_completed_without_error(self):
        """
        Real, deliberate leniency — this endpoint is called from two
        different Step 2 exit paths (a posted OpeningBalanceSession,
        or "Bengkel Baru"), and there is no real state corruption risk
        in it succeeding a second time; a stray double-call should
        never surface a confusing error to the owner.
        """
        self._complete_step_one()
        self.client.post("/api/organizations/mine/complete-onboarding/")
        second = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(second.status_code, status.HTTP_200_OK)

    def test_response_includes_full_organization_data(self):
        self._complete_step_one()
        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.data["organization"]["phone"], "0812-3456-7890")
        self.assertEqual(resp.data["organization"]["invoice_code"], "AM")

class OnboardingCompleteReadinessTests(APITestCase):
    """
    18 Sep 2026 — real, direct proof of the gap found while building
    the Opening Balance frontend wizard (which turned out to already
    exist, as OnboardingOverlay.tsx). OrganizationOnboardingCompleteView
    is called identically from both of that overlay's Step 2 exit
    paths — this proves the "Bengkel Baru" path (no OpeningBalanceSession
    ever created) no longer leaves the shop blocked by its own very
    next screen, and that the real, posted-session path is left
    completely untouched by this fix.
    """

    def setUp(self):
        self.org = Organization.objects.create(
            name="Arya Motor", invoice_code="AM",
            phone="081234567890", address="Jl. Contoh No. 1",
        )
        self.owner = CustomUser.objects.create_user(
            email="owner.onboardingcomplete@test.id", password="pass12345!", full_name="Owner",
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        self.client.force_authenticate(user=self.owner)

    def test_fresh_start_path_resolves_readiness(self):
        """THE real regression test — before this fix, calling this
        endpoint with no OpeningBalanceSession at all left the org
        genuinely unready immediately after 'completing' onboarding."""
        self.assertFalse(OpeningBalanceSession.objects.filter(organization=self.org).exists())

        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        result = check_organization_readiness(self.org)
        self.assertTrue(result["ready"])

    def test_fresh_start_path_creates_a_confirmed_zero_session(self):
        self.client.post("/api/organizations/mine/complete-onboarding/")
        session = OpeningBalanceSession.objects.get(organization=self.org)
        self.assertIsNotNone(session.confirmed_zero_at)
        self.assertEqual(session.confirmed_zero_by_id, self.owner.id)

    def test_fresh_start_path_seeds_coa_and_a_period(self):
        self.assertFalse(Account.objects.filter(organization=self.org).exists())
        self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertTrue(Account.objects.filter(organization=self.org).exists())
        today = date.today()
        self.assertTrue(
            AccountingPeriod.objects.filter(organization=self.org, year=today.year, month=today.month).exists()
        )

    def test_posted_session_path_is_left_untouched(self):
        """Real proof this fix never interferes with the OTHER exit
        path — a session that already exists and is already POSTED
        must not be re-created or re-confirmed."""
        from apps.accounting.models import OpeningBalanceCashLine

        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        session = OpeningBalanceSession.objects.create(organization=self.org, start_date=date.today())
        OpeningBalanceCashLine.objects.create(organization=self.org, session=session, account_code="1001", amount="100000")
        # Real, valid balancing line so post() succeeds cleanly.
        from apps.accounting.models import OpeningBalanceOtherLine
        OpeningBalanceOtherLine.objects.create(
            organization=self.org, session=session, account_code="3001",
            side=OpeningBalanceOtherLine.Side.CREDIT, amount="100000",
        )
        session.post(posted_by=self.owner)
        self.assertEqual(OpeningBalanceSession.objects.filter(organization=self.org).count(), 1)

        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        session.refresh_from_db()
        self.assertEqual(session.status, OpeningBalanceSession.Status.POSTED)
        self.assertIsNone(session.confirmed_zero_at)  # never touched — it was POSTED, not zero-confirmed
        self.assertEqual(OpeningBalanceSession.objects.filter(organization=self.org).count(), 1)  # no second one created

    def test_missing_profile_still_blocked(self):
        """Regression proof — the existing Step-1-must-come-first
        guard is completely unaffected by this fix."""
        bare_org = Organization.objects.create(name="Bengkel Belum Lengkap")
        owner = CustomUser.objects.create_user(
            email="owner.bareorg@test.id", password="pass12345!", full_name="Owner",
        )
        OrganizationMembership.objects.create(organization=bare_org, user=owner, role="owner", is_active=True)
        self.client.force_authenticate(user=owner)

        resp = self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(OpeningBalanceSession.objects.filter(organization=bare_org).exists())

    def test_calling_it_twice_does_not_duplicate_seeding_or_sessions(self):
        """Real safety proof — seed_chart_of_accounts()/
        ensure_current_month_period() are called unconditionally on
        every call; this confirms that's genuinely safe."""
        self.client.post("/api/organizations/mine/complete-onboarding/")
        account_count_after_first = Account.objects.filter(organization=self.org).count()

        self.client.post("/api/organizations/mine/complete-onboarding/")
        self.assertEqual(Account.objects.filter(organization=self.org).count(), account_count_after_first)
        self.assertEqual(OpeningBalanceSession.objects.filter(organization=self.org).count(), 1)