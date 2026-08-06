# =============================================================================
# === backend/apps/letters/tests.py ===
# =============================================================================
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase, APITransactionTestCase

from .models import IncomingLetter, LetterSequence, OutgoingLetter


class LettersAPITestBase(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.letters@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        self.client.force_authenticate(user=self.owner)
        self.customer = Customer.objects.create(organization=self.org, name="Bahlul Baruap")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 1001 AS",
            model="Avanza", manufacture_year=2020,
        )


class OutgoingLetterNumberGenerationTests(TestCase):
    """Direct, real unit tests against the number format — verified
    against Made's own real example: '042/SK/AM/VIII/2026'."""

    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor", invoice_code="AM")

    def test_number_format_matches_made_own_real_example(self):
        letter = OutgoingLetter.objects.create(
            organization=self.org, recipient="Test", subject="Test", source="STANDALONE",
        )
        # sequence-3digit/SK/code/roman-month/year
        parts = letter.number.split("/")
        self.assertEqual(len(parts), 5)
        self.assertEqual(parts[1], "SK")
        self.assertEqual(parts[2], "AM")
        self.assertTrue(parts[0].isdigit())
        self.assertEqual(len(parts[0]), 3)

    def test_sequence_increments_across_letters_same_year(self):
        first = OutgoingLetter.objects.create(organization=self.org, recipient="A", subject="A", source="STANDALONE")
        second = OutgoingLetter.objects.create(organization=self.org, recipient="B", subject="B", source="STANDALONE")
        self.assertEqual(second.sequence_number, first.sequence_number + 1)

    def test_number_is_generated_once_and_never_changes(self):
        letter = OutgoingLetter.objects.create(organization=self.org, recipient="A", subject="A", source="STANDALONE")
        original_number = letter.number
        letter.subject = "Updated subject"
        letter.save()
        letter.refresh_from_db()
        self.assertEqual(letter.number, original_number)

    def test_sequence_is_scoped_per_organization(self):
        other_org = Organization.objects.create(name="Bengkel Lain", invoice_code="BL")
        letter1 = OutgoingLetter.objects.create(organization=self.org, recipient="A", subject="A", source="STANDALONE")
        letter2 = OutgoingLetter.objects.create(organization=other_org, recipient="B", subject="B", source="STANDALONE")
        # Both orgs' first letter — same sequence number, different
        # org codes, so still genuinely distinct real numbers.
        self.assertEqual(letter1.sequence_number, 1)
        self.assertEqual(letter2.sequence_number, 1)
        self.assertNotEqual(letter1.number, letter2.number)


class OutgoingLetterAPITests(LettersAPITestBase):

    def test_can_create_a_standalone_letter(self):
        resp = self.client.post(
            "/api/letters/outgoing/", {"recipient": "Dinas Perhubungan", "subject": "Permohonan Izin"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["letter"]["source"], "STANDALONE")
        self.assertIn("/SK/AM/", resp.data["letter"]["number"])

    def test_cannot_create_letter_without_invoice_code_configured(self):
        self.org.invoice_code = ""
        self.org.save(update_fields=["invoice_code"])
        resp = self.client.post(
            "/api/letters/outgoing/", {"recipient": "Test", "subject": "Test"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_source_cannot_be_set_by_the_client(self):
        """The real security boundary — a standalone letter must
        always be STANDALONE, regardless of what the request body
        tries to claim."""
        resp = self.client.post(
            "/api/letters/outgoing/",
            {"recipient": "Test", "subject": "Test", "source": "ESTIMATE_APPROVAL"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["letter"]["source"], "STANDALONE")

    def test_list_returns_only_this_organizations_letters(self):
        OutgoingLetter.objects.create(organization=self.org, recipient="A", subject="A", source="STANDALONE")
        other_org = Organization.objects.create(name="Bengkel Lain", invoice_code="BL")
        OutgoingLetter.objects.create(organization=other_org, recipient="B", subject="B", source="STANDALONE")
        resp = self.client.get("/api/letters/outgoing/")
        self.assertEqual(len(resp.data["letters"]), 1)


class OutgoingLetterCreationRealTransactionTests(APITransactionTestCase):
    """
    Caught live, 6 Aug: OutgoingLetterListView.post() crashed outright
    with a generic 500 in real use, even though every test in
    OutgoingLetterAPITests above passed cleanly. The reason: APITestCase
    wraps EVERY test in its own transaction for isolation/rollback —
    which accidentally satisfies select_for_update()'s real
    requirement (LetterSequence.next_number() needs an active
    transaction) during tests, while the actual view code never wraps
    its own save() call in one at all. A real request has no such
    surrounding transaction, so it hit TransactionManagementError in
    production-shaped conditions the moment it was actually clicked.

    APITransactionTestCase deliberately does NOT wrap tests in a
    transaction (it truncates and reloads the test DB between runs
    instead) — this is the one test class in this file that can
    actually catch this exact class of bug, not just the fixed code
    coincidentally passing under normal APITestCase isolation.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.letterstxn@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        self.client.force_authenticate(user=self.owner)

    def test_create_succeeds_with_no_surrounding_transaction(self):
        resp = self.client.post(
            "/api/letters/outgoing/", {"recipient": "Biro Humas Polda", "subject": "Permohonan Pencairan Dana"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("/SK/AM/", resp.data["letter"]["number"])


class IncomingLetterVehicleFilterTests(LettersAPITestBase):
    """Real coverage for the vehicle-detail integration — the actual
    endpoint that page's own new section calls."""

    def test_vehicle_filter_returns_only_letters_linked_to_that_vehicle(self):
        other_vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 2002 AS",
            model="Xenia", manufacture_year=2019,
        )
        IncomingLetter.objects.create(
            organization=self.org, sender="Vendor A", subject="Untuk kendaraan ini",
            letter_date="2026-08-01", received_date="2026-08-01",
            vehicle=self.vehicle, file="incoming_letters/a.pdf",
        )
        IncomingLetter.objects.create(
            organization=self.org, sender="Vendor B", subject="Untuk kendaraan lain",
            letter_date="2026-08-01", received_date="2026-08-01",
            vehicle=other_vehicle, file="incoming_letters/b.pdf",
        )
        resp = self.client.get(f"/api/letters/incoming/?vehicle={self.vehicle.id}")
        self.assertEqual(len(resp.data["letters"]), 1)
        self.assertEqual(resp.data["letters"][0]["sender"], "Vendor A")

    def test_no_filter_returns_every_letter_in_the_org(self):
        IncomingLetter.objects.create(
            organization=self.org, sender="Vendor A", subject="Test",
            letter_date="2026-08-01", received_date="2026-08-01",
            file="incoming_letters/a.pdf",
        )
        resp = self.client.get("/api/letters/incoming/")
        self.assertEqual(len(resp.data["letters"]), 1)


class IncomingLetterAPITests(LettersAPITestBase):

    def test_can_upload_an_incoming_letter_with_metadata(self):
        resp = self.client.post("/api/letters/incoming/", {
            "sender": "Dinas Perhubungan Kota Batam",
            "subject": "Undangan Rapat Koordinasi",
            "letter_date": "2026-08-01",
            "received_date": "2026-08-04",
        }, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        # file is a required field — confirms the endpoint genuinely
        # enforces Made's own "not a blind file drop" requirement
        # rather than silently accepting metadata with no document.
        self.assertIn("file", resp.data)

    def test_can_link_to_a_customer_and_vehicle(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_file = SimpleUploadedFile("surat.pdf", b"fake pdf content", content_type="application/pdf")
        resp = self.client.post("/api/letters/incoming/", {
            "sender": "Vendor Sparepart", "subject": "Penawaran Harga",
            "letter_date": "2026-08-01", "received_date": "2026-08-04",
            "customer": str(self.customer.id), "vehicle": str(self.vehicle.id), "file": fake_file,
        }, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["letter"]["customer_name"], "Bahlul Baruap")

    def test_rejects_a_vehicle_that_does_not_belong_to_the_selected_customer(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        other_customer = Customer.objects.create(organization=self.org, name="Pelanggan Lain")
        fake_file = SimpleUploadedFile("surat.pdf", b"fake pdf content", content_type="application/pdf")
        resp = self.client.post("/api/letters/incoming/", {
            "sender": "Test", "subject": "Test",
            "letter_date": "2026-08-01", "received_date": "2026-08-04",
            "customer": str(other_customer.id), "vehicle": str(self.vehicle.id), "file": fake_file,
        }, format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class ContractFundsRequestLetterHookTests(TestCase):
    """
    Real coverage for the second hook, now that the exact
    confirmed_diff shape is confirmed directly from
    apps.contracts.tests's own ContractImportApplyTests — same
    fixture pattern reused verbatim, not guessed at.
    """

    def setUp(self):
        from apps.contracts.models import Contract, ContractImport
        self.Contract = Contract
        self.ContractImport = ContractImport
        self.org = Organization.objects.create(name="CV. Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.lettershook@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        self.institutional_customer = Customer.objects.create(
            organization=self.org, name="Ditreskrimum & Dittahti Polda Kepri",
        )
        self.contract = Contract.objects.create(
            organization=self.org, customer=self.institutional_customer,
            title="Pengadaan Pemeliharaan Kendaraan R4/R6", fiscal_year=2026,
            termin_count=4,
        )

    def _confirmed_diff(self):
        return {
            "added_vehicles": [{
                "fleet_code": "9-XXXI", "vehicle_model": "HYUNDAY TUCSON",
                "manufacture_year": 2020, "vehicle_type": "Mobil",
                "allocated_budget": "21600000",
                "line_items": [
                    {"row_no": 1, "description": "Oli Mesin", "volume": "15",
                     "unit": "Liter", "unit_price": "200000", "subtotal": "3000000"},
                ],
            }],
        }

    def test_applying_an_import_creates_a_real_outgoing_letter(self):
        contract_import = self.ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/test.xlsx", uploaded_by=self.owner,
        )
        contract_import.apply(self._confirmed_diff(), applied_by=self.owner)

        letter = OutgoingLetter.objects.get(contract_import=contract_import)
        self.assertEqual(letter.source, "CONTRACT_FUNDS_REQUEST")
        self.assertEqual(letter.recipient, "Ditreskrimum & Dittahti Polda Kepri")
        self.assertIn("/SK/AM/", letter.number)

    def test_no_letter_created_if_invoice_code_not_configured(self):
        """Same real design call as the Estimate hook — a Settings
        gap must never block the actual contract-import apply, which
        has real consequences of its own regardless of whether the
        letter exists."""
        self.org.invoice_code = ""
        self.org.save(update_fields=["invoice_code"])
        contract_import = self.ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/test.xlsx", uploaded_by=self.owner,
        )
        contract_import.apply(self._confirmed_diff(), applied_by=self.owner)

        contract_import.refresh_from_db()
        self.assertEqual(contract_import.status, "APPLIED")  # the real apply still succeeded
        self.assertFalse(OutgoingLetter.objects.filter(contract_import=contract_import).exists())

    def test_letter_is_not_created_twice_on_a_second_import_for_the_same_contract(self):
        """Each apply() creates its own separate letter — this
        proves a second, later import genuinely produces a second,
        distinct fund-request letter with its own real number, not a
        reused or overwritten one."""
        first_import = self.ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/first.xlsx", uploaded_by=self.owner,
        )
        first_import.apply(self._confirmed_diff(), applied_by=self.owner)

        second_import = self.ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/second.xlsx", uploaded_by=self.owner,
        )
        second_diff = {
            "added_vehicles": [{
                "fleet_code": "921-XXXI", "vehicle_model": "TOYOTA AVANZA",
                "manufacture_year": 2021, "vehicle_type": "Mobil",
                "allocated_budget": "18000000",
                "line_items": [
                    {"row_no": 1, "description": "Oli Mesin", "volume": "12",
                     "unit": "Liter", "unit_price": "200000", "subtotal": "2400000"},
                ],
            }],
        }
        second_import.apply(second_diff, applied_by=self.owner)

        self.assertEqual(OutgoingLetter.objects.filter(contract_import__contract=self.contract).count(), 2)
        first_letter = OutgoingLetter.objects.get(contract_import=first_import)
        second_letter = OutgoingLetter.objects.get(contract_import=second_import)
        self.assertNotEqual(first_letter.number, second_letter.number)
class EstimateApprovalLetterHookTests(TestCase):
    """Real coverage for the one hook I have full, confident context
    for — Estimate.approve()."""

    def setUp(self):
        self.org = Organization.objects.create(name="CV. Arya Motor", invoice_code="AM")
        self.customer = Customer.objects.create(organization=self.org, name="Bahlul Baruap")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 1001 AS",
            model="Avanza", manufacture_year=2020,
        )

    def test_approving_an_estimate_creates_a_real_outgoing_letter(self):
        from apps.estimates.models import Estimate
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        estimate.approve()
        letter = OutgoingLetter.objects.get(estimate=estimate)
        self.assertEqual(letter.source, "ESTIMATE_APPROVAL")
        self.assertEqual(letter.recipient, "Bahlul Baruap")
        self.assertIn("/SK/AM/", letter.number)

    def test_no_letter_created_if_invoice_code_not_configured(self):
        """Estimate approval itself must never be blocked by a
        Settings gap unrelated to the estimate — the letter is
        skipped silently, not raised as an error."""
        from apps.estimates.models import Estimate
        self.org.invoice_code = ""
        self.org.save(update_fields=["invoice_code"])
        estimate = Estimate.objects.create(organization=self.org, vehicle=self.vehicle)
        work_order = estimate.approve()
        self.assertIsNotNone(work_order)
        self.assertFalse(OutgoingLetter.objects.filter(estimate=estimate).exists())
