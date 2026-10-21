"""
Phase 21, Task 21.3 (20 Oct 2026) — Daftar Jasa: one price per vehicle
class plus a default (Made's 12 Sep note), owner-only changes, a full
change history, and body_style restricted to the agreed class list.
"""
import pathlib
import re
from decimal import Decimal

from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import (VEHICLE_CLASSES, Customer, ServiceItem, ServiceItemChange,
                     Vehicle, normalise_vehicle_class)


class NormaliseVehicleClassTests(SimpleTestCase):
    def test_spelling_variants_map_to_the_canonical_class(self):
        for raw, expected in [("suv", "SUV"), (" SUV ", "SUV"), ("Mpv", "MPV"),
                              ("pick up", "Pick-up"), ("PICKUP", "Pick-up"), ("hatchback", "Hatchback")]:
            self.assertEqual(normalise_vehicle_class(raw), expected, raw)

    def test_blank_and_unknown_mean_no_class(self):
        for raw in ("", None, "Compact", "edan", "Minibus"):
            self.assertEqual(normalise_vehicle_class(raw), "", raw)


class ServiceItemVehicleClassSyncTests(SimpleTestCase):
    """The frontend dropdown and the backend validation must offer the same
    list (Cheat Sheet section 7: one supported set, never two that drift)."""

    def test_frontend_list_matches_backend(self):
        ts = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "lib" / "api" / "service.ts"
        if not ts.exists():
            self.skipTest("frontend/ not present in this checkout")
        match = re.search(r"export const VEHICLE_CLASSES = \[([^\]]*)\]", ts.read_text())
        self.assertIsNotNone(match, "VEHICLE_CLASSES not found in frontend/lib/api/service.ts")
        frontend = re.findall(r'"([^"]+)"', match.group(1))
        self.assertEqual(frontend, VEHICLE_CLASSES)


class ServiceItemBase(APITestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        self.owner = CustomUser.objects.create_user(
            email="owner.jasa@test.id", password="pass12345!", full_name="Made Owner",
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        self.staff = CustomUser.objects.create_user(
            email="staff.jasa@test.id", password="pass12345!", full_name="SA Staff",
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.staff, role="member", is_active=True)
        self.client.force_authenticate(user=self.owner)

    def _tune_up(self):
        return ServiceItem.record(
            organization=self.org, name="Tune-up", default_price="300000",
            class_prices={"SUV": "400000", "MPV": "350000"}, created_by=self.owner,
        )


class ServiceItemModelTests(ServiceItemBase):

    def test_record_saves_default_and_class_prices_and_logs_creation(self):
        item = self._tune_up()
        self.assertEqual(item.default_price, Decimal("300000.00"))
        self.assertEqual({p.body_style: p.price for p in item.class_prices.all()},
                         {"SUV": Decimal("400000.00"), "MPV": Decimal("350000.00")})
        self.assertEqual(item.changes.get().field_label, "Dibuat")

    def test_price_for_uses_class_price_then_default(self):
        item = self._tune_up()
        self.assertEqual(item.price_for("SUV"), (Decimal("400000.00"), "class"))
        self.assertEqual(item.price_for("suv"), (Decimal("400000.00"), "class"))
        self.assertEqual(item.price_for("Sedan"), (Decimal("300000.00"), "default"))
        self.assertEqual(item.price_for(""), (Decimal("300000.00"), "default"))
        self.assertEqual(item.price_for("Compact"), (Decimal("300000.00"), "default"))

    def test_price_for_accepts_a_vehicle(self):
        item = self._tune_up()
        customer = Customer.objects.create(organization=self.org, name="Budi")
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=customer, plate_number="BP 1 JS",
            manufacture_year=2020, vehicle_type="Mobil", model="Avanza", body_style="MPV",
        )
        self.assertEqual(item.price_for(vehicle), (Decimal("350000.00"), "class"))

    def test_record_rejects_bad_input_and_writes_nothing(self):
        for kwargs, message in [
            ({"name": "  ", "default_price": "1"}, "wajib"),
            ({"name": "X", "default_price": "-1"}, "negatif"),
            ({"name": "X", "default_price": "abc"}, "angka"),
            ({"name": "X", "default_price": "1", "class_prices": {"Compact": "5"}}, "tidak dikenal"),
        ]:
            with self.assertRaisesMessage(ValueError, message):
                ServiceItem.record(organization=self.org, **kwargs)
        self.assertFalse(ServiceItem.objects.exists())

    def test_duplicate_name_is_rejected_case_insensitively(self):
        self._tune_up()
        with self.assertRaisesMessage(ValueError, "sudah ada"):
            ServiceItem.record(organization=self.org, name="TUNE-UP", default_price="1")

    def test_apply_edit_logs_each_real_change_once(self):
        item = self._tune_up()
        item.apply_edit(
            changed_by=self.owner, default_price="320000",
            class_prices={"SUV": "450000", "MPV": None, "Sedan": "310000"},
        )
        labels = set(item.changes.exclude(field_label="Dibuat").values_list("field_label", flat=True))
        self.assertEqual(labels, {"Harga Default", "Harga SUV", "Harga MPV", "Harga Sedan"})
        self.assertEqual({p.body_style: p.price for p in item.class_prices.all()},
                         {"SUV": Decimal("450000.00"), "Sedan": Decimal("310000.00")})
        mpv = item.changes.get(field_label="Harga MPV")
        self.assertEqual((mpv.old_value, mpv.new_value), ("Rp 350.000", "(pakai default)"))

    def test_apply_edit_with_no_real_difference_logs_nothing(self):
        item = self._tune_up()
        item.apply_edit(changed_by=self.owner, name="Tune-up", default_price="300000",
                        class_prices={"SUV": "400000"})
        self.assertEqual(item.changes.count(), 1)  # only "Dibuat"

    def test_untouched_fields_stay_untouched(self):
        item = self._tune_up()
        item.apply_edit(changed_by=self.owner, is_active=False)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertEqual(item.default_price, Decimal("300000.00"))
        self.assertEqual(item.class_prices.count(), 2)


class ServiceItemAPITests(ServiceItemBase):

    def test_owner_can_create(self):
        resp = self.client.post("/api/service-items/", {
            "name": "Spooring", "default_price": 150000, "class_prices": {"SUV": 200000},
        }, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["service_item"]["class_prices"], {"SUV": "200000.00"})

    def test_staff_can_read_but_not_change(self):
        item = self._tune_up()
        self.client.force_authenticate(user=self.staff)
        listed = self.client.get("/api/service-items/")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.data["count"], 1)
        self.assertFalse(listed.data["can_edit"])
        create = self.client.post("/api/service-items/", {"name": "X", "default_price": 1}, format="json")
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)
        patch = self.client.patch(f"/api/service-items/{item.id}/", {"default_price": 1}, format="json")
        self.assertEqual(patch.status_code, status.HTTP_403_FORBIDDEN)
        item.refresh_from_db()
        self.assertEqual(item.default_price, Decimal("300000.00"))

    def test_list_returns_classes_and_hides_inactive_by_default(self):
        item = self._tune_up()
        item.apply_edit(changed_by=self.owner, is_active=False)
        resp = self.client.get("/api/service-items/")
        self.assertEqual(resp.data["count"], 0)
        self.assertEqual(resp.data["vehicle_classes"], VEHICLE_CLASSES)
        self.assertTrue(resp.data["can_edit"])
        self.assertEqual(self.client.get("/api/service-items/?include_inactive=true").data["count"], 1)

    def test_patch_only_touches_what_was_sent_and_history_shows_it(self):
        item = self._tune_up()
        resp = self.client.patch(f"/api/service-items/{item.id}/", {"class_prices": {"SUV": 425000}}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["service_item"]["default_price"], "300000.00")
        self.assertEqual(resp.data["service_item"]["class_prices"]["SUV"], "425000.00")
        history = self.client.get(f"/api/service-items/{item.id}/history/").data["changes"]
        self.assertEqual(history[0]["field_label"], "Harga SUV")
        self.assertEqual(history[0]["changed_by_name"], "Made Owner")

    def test_bad_input_is_a_400_with_the_message(self):
        resp = self.client.post("/api/service-items/", {"name": "X", "default_price": -5}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("negatif", resp.data["message"])

    def test_other_shop_cannot_see_or_change_it(self):
        item = self._tune_up()
        other_org = Organization.objects.create(name="Bengkel Lain Jasa", invoice_code="BLJ")
        other = CustomUser.objects.create_user(email="owner.lain.jasa@test.id", password="pass12345!", full_name="Lain")
        OrganizationMembership.objects.create(organization=other_org, user=other, role="owner", is_active=True)
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get("/api/service-items/").data["count"], 0)
        resp = self.client.patch(f"/api/service-items/{item.id}/", {"default_price": 1}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class VehicleBodyStyleTests(ServiceItemBase):

    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(organization=self.org, name="Budi")

    def _create(self, body_style):
        return self.client.post("/api/vehicles/", {
            "customer": str(self.customer.id), "plate_number": "BP 7 JS", "manufacture_year": 2021,
            "vehicle_type": "Mobil", "model": "Avanza", "body_style": body_style,
        }, format="json")

    def test_spelling_is_normalised_on_save(self):
        resp = self._create("suv")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["vehicle"]["body_style"], "SUV")

    def test_blank_is_allowed(self):
        self.assertEqual(self._create("").status_code, status.HTTP_201_CREATED)

    def test_value_outside_the_list_is_rejected(self):
        resp = self._create("Minibus")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("body_style", resp.data["errors"])

    def test_old_value_does_not_block_editing_other_fields(self):
        """Production has 'Compact' and 'edan' (19 Oct audit). Editing such a
        vehicle's colour must not fail just because its old class is off-list."""
        vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 8 JS",
            manufacture_year=2019, vehicle_type="Mobil", model="Brio", body_style="Compact",
        )
        resp = self.client.put(f"/api/vehicles/{vehicle.id}/",
                               {"body_style": "Compact", "color": "Merah"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        vehicle.refresh_from_db()
        self.assertEqual((vehicle.body_style, vehicle.color), ("Compact", "Merah"))
        resp = self.client.put(f"/api/vehicles/{vehicle.id}/", {"body_style": "Hatchback"}, format="json")
        self.assertEqual(resp.data["vehicle"]["body_style"], "Hatchback")
