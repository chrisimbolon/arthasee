# =============================================================================
# === backend/apps/analytics/tests.py ===
# =============================================================================
from datetime import date, timedelta
from decimal import Decimal

from apps.accounting.models import Account, JournalEntry
from apps.authentication.models import CustomUser
from apps.organizations.models import Organization, OrganizationMembership
from apps.service.models import Customer, ServiceRecord, Vehicle
from apps.workorders.models import Mechanic, WorkOrder, WorkOrderStage
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from . import growth


def _shift_month(d, delta):
    """Same month-arithmetic shape as growth.py's own _last_n_month_starts."""
    y, m = d.year, d.month + delta
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


class GrowthAnalyticsTestBase(TestCase):

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.customer = Customer.objects.create(organization=self.org, name="Test Customer")
        self.vehicle = Vehicle.objects.create(
            organization=self.org, customer=self.customer, plate_number="BP 1234",
            manufacture_year=2020, vehicle_type="Mobil", model="Test Model",
        )

    def _new_work_order(self, status="OPEN", assigned_to=None):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, assigned_to=assigned_to)
        wo.status = status
        wo.save(update_fields=["status"])
        return wo


class MechanicUtilizationTests(GrowthAnalyticsTestBase):

    def test_counts_mechanic_directly_assigned_to_in_progress_workorder(self):
        m1 = Mechanic.objects.create(organization=self.org, name="Budi")
        m2 = Mechanic.objects.create(organization=self.org, name="Andi")
        self._new_work_order(status="IN_PROGRESS", assigned_to=m1)
        self._new_work_order(status="OPEN", assigned_to=m2)  # not IN_PROGRESS — must not count

        result = growth.mechanic_utilization(self.org)
        self.assertEqual(result["mechanics_working"], 1)
        self.assertEqual(result["mechanics_total"], 2)

    def test_counts_mechanic_via_active_stage_when_parent_is_in_progress(self):
        m = Mechanic.objects.create(organization=self.org, name="Citra")
        wo = self._new_work_order(status="IN_PROGRESS")
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Body Repair", sequence=1,
            assigned_to=m, started_at=timezone.now(), completed_at=None,
        )
        result = growth.mechanic_utilization(self.org)
        self.assertEqual(result["mechanics_working"], 1)

    def test_does_not_count_mechanic_when_parent_workorder_is_in_qc(self):
        """
        The real, deliberate distinction — a stage can still sit open
        while its parent WorkOrder has already moved to QC (close()
        only force-completes stragglers at the QC->DONE transition).
        QC means being inspected, not actively worked.
        """
        m = Mechanic.objects.create(organization=self.org, name="Dedi")
        wo = self._new_work_order(status="QC")
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Painting", sequence=1,
            assigned_to=m, started_at=timezone.now(), completed_at=None,
        )
        result = growth.mechanic_utilization(self.org)
        self.assertEqual(result["mechanics_working"], 0)

    def test_inactive_mechanic_excluded_from_total(self):
        Mechanic.objects.create(organization=self.org, name="Aktif", is_active=True)
        Mechanic.objects.create(organization=self.org, name="Nonaktif", is_active=False)
        result = growth.mechanic_utilization(self.org)
        self.assertEqual(result["mechanics_total"], 1)

    def test_mechanic_counted_once_even_if_assigned_both_ways(self):
        """
        A mechanic directly assigned to the WorkOrder AND also
        assigned to one of its own stages must still count as ONE
        working mechanic — the set-union logic must deduplicate.
        """
        m = Mechanic.objects.create(organization=self.org, name="Eka")
        wo = self._new_work_order(status="IN_PROGRESS", assigned_to=m)
        WorkOrderStage.objects.create(
            organization=self.org, work_order=wo, name="Tahap 1", sequence=1,
            assigned_to=m, started_at=timezone.now(), completed_at=None,
        )
        result = growth.mechanic_utilization(self.org)
        self.assertEqual(result["mechanics_working"], 1)


class WorkOrderQueueStatusTests(GrowthAnalyticsTestBase):

    def test_counts_by_status_excluding_cancelled(self):
        self._new_work_order(status="OPEN")
        self._new_work_order(status="OPEN")
        self._new_work_order(status="IN_PROGRESS")
        self._new_work_order(status="QC")
        self._new_work_order(status="CANCELLED")

        result = growth.work_order_queue_status(self.org)
        self.assertEqual(result["open"], 2)
        self.assertEqual(result["in_progress"], 1)
        self.assertEqual(result["qc"], 1)
        self.assertEqual(result["done"], 0)


class RevenueTrendTests(GrowthAnalyticsTestBase):

    def test_buckets_by_month_and_zero_fills_quiet_months(self):
        revenue = Account.objects.get(organization=self.org, code="4001")
        ar = Account.objects.get(organization=self.org, code="1201")

        JournalEntry.post(
            organization=self.org, posting_date=_shift_month(date.today(), -2),
            source=JournalEntry.Source.MANUAL,
            lines=[{"account": ar, "debit": Decimal("100000")}, {"account": revenue, "credit": Decimal("100000")}],
        )
        JournalEntry.post(
            organization=self.org, posting_date=date.today(), source=JournalEntry.Source.MANUAL,
            lines=[{"account": ar, "debit": Decimal("50000")}, {"account": revenue, "credit": Decimal("50000")}],
        )

        result = growth.revenue_trend(self.org, months=3)
        months = result["months"]
        self.assertEqual(len(months), 3)
        self.assertEqual(months[0]["revenue"], Decimal("100000"))  # 2 months ago
        self.assertEqual(months[1]["revenue"], Decimal("0"))       # quiet month, zero-filled
        self.assertEqual(months[2]["revenue"], Decimal("50000"))   # current month

    def test_projected_net_income_is_simple_average_of_recent_months(self):
        revenue = Account.objects.get(organization=self.org, code="4001")
        ar = Account.objects.get(organization=self.org, code="1201")
        for i, amount in enumerate([Decimal("100000"), Decimal("200000"), Decimal("300000")]):
            JournalEntry.post(
                organization=self.org, posting_date=_shift_month(date.today(), -(2 - i)),
                source=JournalEntry.Source.MANUAL,
                lines=[{"account": ar, "debit": amount}, {"account": revenue, "credit": amount}],
            )
        result = growth.revenue_trend(self.org, months=3)
        # (100000 + 200000 + 300000) / 3 = 200000 — no COGS/expenses
        # posted, so net_income equals revenue for each month.
        self.assertEqual(result["projected_next_net_income"], Decimal("200000"))

    def test_projection_excludes_pre_history_zero_months(self):
        """
        Real bug, caught live in production (Aug 12 2026) — the
        projection was including months from BEFORE this system
        existed (zero-filled the same way a genuinely quiet month
        would be) in its average, silently dragging a real, healthy
        average down by roughly a third the very first time this
        feature was used against real data. This is the permanent
        regression test for that fix.
        """
        revenue = Account.objects.get(organization=self.org, code="4001")
        ar = Account.objects.get(organization=self.org, code="1201")
        # Only the last 2 months have real activity — everything
        # before that is genuinely pre-history, nothing ever posted.
        for i, amount in enumerate([Decimal("150000"), Decimal("300000")]):
            JournalEntry.post(
                organization=self.org, posting_date=_shift_month(date.today(), -(1 - i)),
                source=JournalEntry.Source.MANUAL,
                lines=[{"account": ar, "debit": amount}, {"account": revenue, "credit": amount}],
            )
        result = growth.revenue_trend(self.org, months=6)
        # If the old, broken method were still in place, this would
        # average across 3 months including one pre-history zero:
        # (0 + 150000 + 300000) / 3 = 150000 — a wrong, skewed number,
        # exactly what the real screenshot showed. The fix must
        # average ONLY the 2 real months: (150000 + 300000) / 2 = 225000.
        self.assertEqual(result["projected_next_net_income"], Decimal("225000"))
        self.assertEqual(result["projected_months_used"], 2)

class JobVolumeTrendTests(GrowthAnalyticsTestBase):

    def test_created_bucketed_correctly(self):
        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle)
        last_month = _shift_month(date.today(), -1)
        WorkOrder.objects.filter(pk=wo.pk).update(
            created_at=timezone.make_aware(timezone.datetime(last_month.year, last_month.month, 15)),
        )
        result = growth.job_volume_trend(self.org, months=2)
        self.assertEqual(result[0]["created"], 1)  # last month
        self.assertEqual(result[1]["created"], 0)  # current month

    def test_completed_uses_service_record_created_at_not_workorder_updated_at(self):
        """
        Real proof of the design choice — if this used
        WorkOrder.updated_at instead of ServiceRecord.created_at, this
        test would show the completion landing in the WRONG month
        (whenever `notes` was last touched), not the real completion
        month.
        """
        record = ServiceRecord.objects.create(
            organization=self.org, vehicle=self.vehicle, service_date=date.today(),
            odometer_km=1000, issue_description="Test",
        )
        last_month = _shift_month(date.today(), -1)
        ServiceRecord.objects.filter(pk=record.pk).update(
            created_at=timezone.make_aware(timezone.datetime(last_month.year, last_month.month, 10)),
        )

        wo = WorkOrder.objects.create(organization=self.org, vehicle=self.vehicle, service_record=record)
        wo.status = "DONE"
        wo.notes = "unrelated edit, touches updated_at to TODAY"
        wo.save(update_fields=["status", "notes", "updated_at"])

        result = growth.job_volume_trend(self.org, months=2)
        self.assertEqual(result[0]["completed"], 1)  # correctly last month
        self.assertEqual(result[1]["completed"], 0)  # NOT current month, despite updated_at being today


class CustomerGrowthTrendTests(GrowthAnalyticsTestBase):

    def test_counts_new_customers_per_month(self):
        other = Customer.objects.create(organization=self.org, name="Another Customer")
        last_month = _shift_month(date.today(), -1)
        Customer.objects.filter(pk=other.pk).update(
            created_at=timezone.make_aware(timezone.datetime(last_month.year, last_month.month, 20)),
        )

        result = growth.customer_growth_trend(self.org, months=2)
        self.assertEqual(result["months"][0]["new_customers"], 1)  # last month
        self.assertEqual(result["months"][1]["new_customers"], 1)  # current month (self.customer, from setUp)
        self.assertEqual(result["total_customers"], 2)


class AnalyticsAPITests(APITestCase):
    """
    Lean HTTP-level smoke tests — the real logic correctness is
    already proven by the classes above; this layer only proves the
    thin views are wired correctly.
    """

    def setUp(self):
        self.org = Organization.objects.create(name="Arya Motor", invoice_code="AM")
        call_command("seed_coa", organization=str(self.org.id), verbosity=0)
        self.owner = CustomUser.objects.create_user(
            email="owner.analytics@test.id", password="pass12345!",
            full_name="Made Owner", role=CustomUser.Role.OWNER,
        )
        OrganizationMembership.objects.create(organization=self.org, user=self.owner, role="owner", is_active=True)
        self.client.force_authenticate(user=self.owner)

    def test_revenue_trend_endpoint(self):
        resp = self.client.get("/api/analytics/revenue-trend/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("months", resp.data)
        self.assertIn("projected_next_net_income", resp.data)

    def test_mechanic_utilization_endpoint(self):
        resp = self.client.get("/api/analytics/mechanic-utilization/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("mechanics_working", resp.data)

    def test_queue_status_endpoint(self):
        resp = self.client.get("/api/analytics/queue-status/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("open", resp.data)

    def test_job_volume_trend_endpoint_respects_months_param(self):
        resp = self.client.get("/api/analytics/job-volume-trend/?months=6")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["months"]), 6)

    def test_customer_growth_trend_endpoint(self):
        resp = self.client.get("/api/analytics/customer-growth-trend/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("total_customers", resp.data)
