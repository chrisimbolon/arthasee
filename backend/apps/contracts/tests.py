# =============================================================================
# === backend/apps/contracts/tests.py ===
# =============================================================================
import io
from decimal import Decimal

import openpyxl
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, Vehicle
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import Contract, ContractImport, ContractLineItem, ContractVehicle
from .parsing import (ContractParseError, diff_against_contract,
                      parse_hps_workbook, parse_rupiah)


def _build_test_workbook(rows):
    """Small helper — builds an in-memory .xlsx matching the real HPS
    template's structure, so tests read like the actual document
    rather than an abstract fixture."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


HEADER_ROWS = [
    ["PEKERJAAN : PENGADAAN PEMELIHARAAN DAN PERAWATAN..."],
    ["[REDACTED REFERENCE LINE]"],
    [],
    ["NO", "ITEM PEKERJAAN", "VOL", "SATUAN", "HARGA SATUAN", "JUMLAH"],
]


class ParseRupiahTests(TestCase):
    """
    Proves the actual real-world inconsistencies found in the one
    real HPS document reviewed for this project parse correctly —
    not just the clean, ideal case.
    """

    def test_plain_rp_format(self):
        self.assertEqual(parse_rupiah("Rp 200.000"), Decimal("200000"))

    def test_real_typo_rp_with_period(self):
        """The actual typo found in Group I, row 9 of the real Polda
        Kepri document: 'Rp.' instead of 'Rp'."""
        self.assertEqual(parse_rupiah("Rp. 4.000.000"), Decimal("4000000"))

    def test_numeric_cell_value(self):
        self.assertEqual(parse_rupiah(21600000), Decimal("21600000"))

    def test_comma_decimal_defensive_case(self):
        """Never observed in the real document, but Indonesian
        formatting could in principle use a comma decimal — must not
        be confused with '.' as a thousands separator."""
        self.assertEqual(parse_rupiah("Rp 1.234,50"), Decimal("1234.50"))

    def test_empty_value_raises(self):
        with self.assertRaises(ContractParseError):
            parse_rupiah("")

    def test_garbage_value_raises(self):
        with self.assertRaises(ContractParseError):
            parse_rupiah("tidak ada harga")


class ParseHpsWorkbookTests(TestCase):
    """
    Built against the VISIBLE structure of the real Polda Kepri HPS
    document (seen as PDF text, not yet the real .xlsx) — see
    parsing.py's own module docstring for why this still needs
    calibration against the real file.
    """

    def test_parses_two_vehicle_groups_with_the_real_typo(self):
        buf = _build_test_workbook(HEADER_ROWS + [
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 21.600.000"],
            [1, "Oli Mesin", 15, "Liter", "Rp 200.000", "Rp 3.000.000"],
            [2, "Filter Oli", 3, "Unit", "Rp 200.000", "Rp 600.000"],
            [9, "Perbaikan kaki-kaki", 1, "Paket", "Rp 4.000.000", "Rp. 4.000.000"],
            ["II", "TOYOTA AVANZA (921-XXXI)", 1, "MOBIL", "", "Rp 21.600.000"],
            [1, "Oli Mesin semi/ full synthetic", 12, "Liter", "Rp 200.000", "Rp 2.400.000"],
            [2, "Filter Oli", 3, "Unit", "Rp 120.000", "Rp 360.000"],
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 10.360.000"],
        ])
        parsed = parse_hps_workbook(buf)

        self.assertEqual(len(parsed.vehicle_groups), 2)
        g1, g2 = parsed.vehicle_groups
        self.assertEqual(g1.vehicle_model, "HYUNDAY TUCSON")
        self.assertEqual(g1.fleet_code, "9-XXXI")
        self.assertEqual(len(g1.line_items), 3)
        # The typo row parsed correctly despite "Rp." instead of "Rp":
        self.assertEqual(g1.line_items[2].subtotal, Decimal("4000000"))
        self.assertEqual(g2.fleet_code, "921-XXXI")
        self.assertEqual(parsed.document_total, Decimal("10360000"))
        self.assertEqual(parsed.computed_total, Decimal("10360000"))

    def test_missing_header_raises_parse_error(self):
        buf = _build_test_workbook([["not", "a", "real", "template"]])
        with self.assertRaises(ContractParseError):
            parse_hps_workbook(buf)

    def test_line_item_before_any_group_header_raises(self):
        """The template assumption genuinely doesn't hold for this
        file — must fail loudly, not silently attach the row to
        nothing."""
        buf = _build_test_workbook(HEADER_ROWS + [
            [1, "Oli Mesin", 15, "Liter", "Rp 200.000", "Rp 3.000.000"],
        ])
        with self.assertRaises(ContractParseError):
            parse_hps_workbook(buf)

    def test_no_vehicle_groups_found_raises(self):
        buf = _build_test_workbook(HEADER_ROWS)
        with self.assertRaises(ContractParseError):
            parse_hps_workbook(buf)

    def test_vehicle_name_without_fleet_code_falls_back_gracefully(self):
        """A malformed vehicle name shouldn't block importing every
        other vehicle in the same file — surfaced as an empty
        fleet_code for a human to fill in during review, not a hard
        failure."""
        buf = _build_test_workbook(HEADER_ROWS + [
            ["I", "SOME VEHICLE WITHOUT A CODE", 1, "MOBIL", "", "Rp 1.000.000"],
            [1, "Oli Mesin", 1, "Liter", "Rp 1.000.000", "Rp 1.000.000"],
        ])
        parsed = parse_hps_workbook(buf)
        self.assertEqual(parsed.vehicle_groups[0].fleet_code, "")
        self.assertEqual(parsed.vehicle_groups[0].vehicle_model, "SOME VEHICLE WITHOUT A CODE")


class ContractsAPITestBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.contracts@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.org, user=self.owner, role="owner", is_active=True,
        )
        self.institutional_customer = Customer.objects.create(
            organization=self.org, name="Ditreskrimum & Dittahti Polda Kepri",
        )
        self.contract = Contract.objects.create(
            organization=self.org, customer=self.institutional_customer,
            title="Pengadaan Pemeliharaan Kendaraan R4/R6", fiscal_year=2026,
            termin_count=4,
        )
        self.client.force_authenticate(user=self.owner)


class DiffAgainstContractTests(ContractsAPITestBase):
    """
    Proves the diff engine correctly classifies every case using
    (fleet_code, source_row_no) as the matching key — not description
    text, which the real document already proves is unstable across
    different vehicles for conceptually-the-same job.
    """

    def setUp(self):
        super().setUp()
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.institutional_customer,
            plate_number="9-XXXI", manufacture_year=2020,
            vehicle_type="Mobil", model="HYUNDAY TUCSON",
        )
        self.contract_vehicle = ContractVehicle.objects.create(
            organization=self.org, contract=self.contract,
            vehicle=self.vehicle, allocated_budget=Decimal("21600000"),
        )
        self.existing_item = ContractLineItem.objects.create(
            organization=self.org, contract_vehicle=self.contract_vehicle,
            source_row_no=1, description="Oli Mesin", volume=Decimal("15"),
            unit="Liter", unit_price=Decimal("200000"), subtotal=Decimal("3000000"),
        )

    def _parsed(self, rows):
        buf = _build_test_workbook(HEADER_ROWS + rows)
        return parse_hps_workbook(buf)

    def test_unchanged_line_is_not_flagged(self):
        parsed = self._parsed([
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 21.600.000"],
            [1, "Oli Mesin", 15, "Liter", "Rp 200.000", "Rp 3.000.000"],
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 3.000.000"],
        ])
        diff = diff_against_contract(parsed, self.contract)
        self.assertEqual(diff["unchanged_count"], 1)
        self.assertEqual(diff["added_items"], [])
        self.assertEqual(diff["changed_items"], [])
        self.assertEqual(diff["removed_items"], [])

    def test_changed_price_is_flagged_with_old_and_new(self):
        parsed = self._parsed([
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 21.600.000"],
            [1, "Oli Mesin", 15, "Liter", "Rp 250.000", "Rp 3.750.000"],  # price went up
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 3.750.000"],
        ])
        diff = diff_against_contract(parsed, self.contract)
        self.assertEqual(len(diff["changed_items"]), 1)
        change = diff["changed_items"][0]
        # existing_li.unit_price/subtotal are read back from real
        # DecimalField(decimal_places=2) columns — Django always
        # returns these quantized to two decimal places, so str()
        # faithfully produces "200000.00", not "200000". The diff
        # function's own str(existing_li.unit_price) call is correct;
        # this assertion was just wrong about what that produces.
        self.assertEqual(change["old"]["unit_price"], "200000.00")
        self.assertEqual(change["new"]["unit_price"], "250000")

    def test_new_line_on_existing_vehicle_is_added_item(self):
        parsed = self._parsed([
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 24.600.000"],
            [1, "Oli Mesin", 15, "Liter", "Rp 200.000", "Rp 3.000.000"],
            [2, "Filter Oli", 3, "Unit", "Rp 200.000", "Rp 600.000"],  # brand new row
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 3.600.000"],
        ])
        diff = diff_against_contract(parsed, self.contract)
        self.assertEqual(len(diff["added_items"]), 1)
        self.assertEqual(diff["added_items"][0]["row_no"], 2)

    def test_missing_line_is_removed_item(self):
        """Simulates a revision that drops row 1 entirely."""
        parsed = self._parsed([
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 0"],
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 0"],
        ])
        diff = diff_against_contract(parsed, self.contract)
        self.assertEqual(len(diff["removed_items"]), 1)
        self.assertEqual(diff["removed_items"][0]["row_no"], 1)

    def test_brand_new_vehicle_is_added_vehicle_not_added_item(self):
        parsed = self._parsed([
            ["I", "HYUNDAY TUCSON (9-XXXI)", 1, "MOBIL", "", "Rp 21.600.000"],
            [1, "Oli Mesin", 15, "Liter", "Rp 200.000", "Rp 3.000.000"],
            ["II", "TOYOTA AVANZA (921-XXXI)", 1, "MOBIL", "", "Rp 2.400.000"],
            [1, "Oli Mesin", 12, "Liter", "Rp 200.000", "Rp 2.400.000"],
            ["", "TOTAL KESELURUHAN", "", "", "", "Rp 5.400.000"],
        ])
        diff = diff_against_contract(parsed, self.contract)
        self.assertEqual(len(diff["added_vehicles"]), 1)
        self.assertEqual(diff["added_vehicles"][0]["fleet_code"], "921-XXXI")
        # Existing vehicle's own unchanged line must not also appear
        # as noise elsewhere:
        self.assertEqual(diff["unchanged_count"], 1)


class ContractImportApplyTests(ContractsAPITestBase):
    """
    Proves the actual mutation logic — the part with real
    consequences if it gets the ordering or the supersede logic
    wrong.
    """

    def test_apply_creates_vehicle_and_line_items_for_new_contract(self):
        """The very first import for a brand-new Contract — no
        separate 'create from scratch' path, just a diff where
        everything happens to be added."""
        contract_import = ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/test.xlsx", uploaded_by=self.owner,
        )
        confirmed_diff = {
            "added_vehicles": [{
                "fleet_code": "9-XXXI",
                "vehicle_model": "HYUNDAY TUCSON",
                "manufacture_year": 2020,  # filled in by the reviewer —
                # never present in the source document itself
                "vehicle_type": "Mobil",
                "allocated_budget": "21600000",
                "line_items": [
                    {"row_no": 1, "description": "Oli Mesin", "volume": "15",
                     "unit": "Liter", "unit_price": "200000", "subtotal": "3000000"},
                ],
            }],
        }

        contract_import.apply(confirmed_diff, applied_by=self.owner)

        self.assertEqual(Vehicle.objects.filter(plate_number="9-XXXI").count(), 1)
        vehicle = Vehicle.objects.get(plate_number="9-XXXI")
        self.assertEqual(vehicle.manufacture_year, 2020)
        cv = ContractVehicle.objects.get(contract=self.contract, vehicle=vehicle)
        self.assertEqual(cv.allocated_budget, Decimal("21600000"))
        line_item = ContractLineItem.objects.get(contract_vehicle=cv, source_row_no=1)
        self.assertEqual(line_item.status, "ACTIVE")
        self.assertEqual(line_item.subtotal, Decimal("3000000"))

        contract_import.refresh_from_db()
        self.assertEqual(contract_import.status, "APPLIED")
        self.assertEqual(contract_import.applied_by, self.owner)
        self.assertIsNotNone(contract_import.applied_at)

    def test_apply_supersedes_old_line_never_hard_deletes(self):
        """The core safety property this whole design exists for: a
        real WorkOrder created earlier may already reference the old
        line item, so it must never vanish, only be marked
        SUPERSEDED with a pointer to what replaced it."""
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.institutional_customer,
            plate_number="9-XXXI", manufacture_year=2020,
            vehicle_type="Mobil", model="HYUNDAY TUCSON",
        )
        cv = ContractVehicle.objects.create(
            organization=self.org, contract=self.contract,
            vehicle=vehicle, allocated_budget=Decimal("21600000"),
        )
        old_item = ContractLineItem.objects.create(
            organization=self.org, contract_vehicle=cv, source_row_no=1,
            description="Oli Mesin", volume=Decimal("15"), unit="Liter",
            unit_price=Decimal("200000"), subtotal=Decimal("3000000"),
        )

        contract_import = ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/revision.xlsx", uploaded_by=self.owner,
        )
        confirmed_diff = {
            "changed_items": [{
                "fleet_code": "9-XXXI", "row_no": 1,
                "old": {"description": "Oli Mesin", "volume": "15", "unit": "Liter",
                        "unit_price": "200000", "subtotal": "3000000"},
                "new": {"description": "Oli Mesin", "volume": "15", "unit": "Liter",
                        "unit_price": "250000", "subtotal": "3750000"},
            }],
        }
        contract_import.apply(confirmed_diff, applied_by=self.owner)

        old_item.refresh_from_db()
        self.assertEqual(old_item.status, "SUPERSEDED")
        self.assertIsNotNone(old_item.superseded_by)

        new_item = old_item.superseded_by
        self.assertEqual(new_item.status, "ACTIVE")
        self.assertEqual(new_item.unit_price, Decimal("250000"))

        # Only ever one ACTIVE row at this exact position — the real
        # guarantee the UniqueConstraint on the model enforces at the
        # DB level, confirmed here at the application level too.
        active_count = ContractLineItem.objects.filter(
            contract_vehicle=cv, source_row_no=1, status="ACTIVE",
        ).count()
        self.assertEqual(active_count, 1)

    def test_cannot_apply_an_already_applied_import(self):
        contract_import = ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/test.xlsx", uploaded_by=self.owner,
            status="APPLIED",
        )
        with self.assertRaises(ValueError):
            contract_import.apply({}, applied_by=self.owner)

    def test_reject_marks_rejected_without_touching_line_items(self):
        contract_import = ContractImport.objects.create(
            organization=self.org, contract=self.contract,
            original_file="contract_imports/test.xlsx", uploaded_by=self.owner,
        )
        contract_import.reject()
        contract_import.refresh_from_db()
        self.assertEqual(contract_import.status, "REJECTED")
        self.assertEqual(ContractLineItem.objects.count(), 0)


class ContractsTenantIsolationTests(ContractsAPITestBase):

    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Bengkel Lain Kontrak")
        self.other_owner = CustomUser.objects.create_user(
            email="owner.othercontracts@test.id", password="pass12345!",
            full_name="Other Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.other_org, user=self.other_owner, role="owner", is_active=True,
        )

    def test_org_b_cannot_see_org_a_contracts(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get("/api/contracts/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 0)

    def test_org_b_cannot_retrieve_org_a_contract_detail(self):
        self.client.force_authenticate(user=self.other_owner)
        resp = self.client.get(f"/api/contracts/{self.contract.id}/")
        self.assertEqual(resp.status_code, 404)
