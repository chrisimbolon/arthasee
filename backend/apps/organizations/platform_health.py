# =============================================================================
# === backend/apps/organizations/platform_health.py ===
# =============================================================================
"""
Arthasee — Platform overview for the super admin (Phase 22, 24 Oct 2026).

One read-only health snapshot per shop, for the person who runs the
platform (Chris), shown on the frontend's /platform page. It answers
"which shops exist, are they being used, and are their books healthy?"
without logging in as anyone.

Deliberately reuses the checks every shop already trusts, never a second
calculation that could drift from them:
  - accounting.services.readiness.check_organization_readiness()
  - accounting.reports.trial_balance()
  - accounting.reports.reconcile_control_account()  (1201, 1301, 2001)
  - core.models.Outbox status (FAILED, and PENDING stuck > 10 minutes)

PRIVACY (agreed 23 Oct 2026): only counts, account totals and event
types leave this module. No customer names, plate numbers, invoice
lines or amounts per customer. PlatformOverviewPrivacyTests checks this.

Health status per shop:
  red    books not balanced, any control-account difference, or a FAILED event
  amber  readiness blocks, a PENDING event stuck > 10 minutes, or onboarding
         not finished
  green  everything else
"""
from datetime import timedelta

from django.utils import timezone

from .models import Organization, OrganizationMembership

CONTROL_ACCOUNTS = ("1201", "1301", "2001")
STUCK_AFTER = timedelta(minutes=10)
ERROR_PREVIEW = 200


def _activity(org, now):
    from apps.invoicing.models import Invoice
    from apps.payments.models import Payment
    from apps.workorders.models import WorkOrder

    week, month = now - timedelta(days=7), now - timedelta(days=30)
    result, last = {}, None
    for key, model in (("work_orders", WorkOrder), ("invoices", Invoice), ("payments", Payment)):
        qs = model.objects.filter(organization=org)
        result[key] = {
            "last_7_days": qs.filter(created_at__gte=week).count(),
            "last_30_days": qs.filter(created_at__gte=month).count(),
        }
        newest = qs.order_by("-created_at").values_list("created_at", flat=True).first()
        if newest and (last is None or newest > last):
            last = newest
    result["last_activity_at"] = last
    return result


def _books(org):
    from apps.accounting.reports import reconcile_control_account, trial_balance

    tb = trial_balance(org)
    controls = []
    for code in CONTROL_ACCOUNTS:
        try:
            r = reconcile_control_account(org, code)
        except ValueError:
            # Account missing / not a control account — reported, not guessed.
            controls.append({"account_code": code, "available": False})
            continue
        controls.append({
            "account_code": code,
            "account_name": r["account_name"],
            "available": True,
            "gl_balance": r["gl_balance"],
            "subledger_total": r["subledger_total"],
            "difference": r["difference"],
            "is_reconciled": r["is_reconciled"],
        })
    return {
        "trial_balance_balanced": tb["is_balanced"],
        "trial_balance_difference": tb["total_debit"] - tb["total_credit"],
        "control_accounts": controls,
    }


def _events(org, now):
    from apps.core.models import Outbox

    qs = Outbox.objects.filter(organization=org)
    failed = qs.filter(status=Outbox.Status.FAILED)
    latest = failed.order_by("-occurred_at").first()
    return {
        "failed": failed.count(),
        "stuck_pending": qs.filter(status=Outbox.Status.PENDING, created_at__lt=now - STUCK_AFTER).count(),
        "last_failure": None if latest is None else {
            "event_type": latest.event_type,
            "occurred_at": latest.occurred_at,
            "attempts": latest.attempts,
            "error": (latest.last_error or "")[:ERROR_PREVIEW],
        },
    }


def _status(onboarding_completed, readiness, books, events):
    reasons_red, reasons_amber = [], []
    if not books["trial_balance_balanced"]:
        reasons_red.append("Neraca saldo tidak seimbang")
    for c in books["control_accounts"]:
        if c["available"] and not c["is_reconciled"]:
            reasons_red.append(f"Akun {c['account_code']} selisih dengan subledger")
    if events["failed"]:
        reasons_red.append(f"{events['failed']} event gagal diposting")
    if readiness["blocks"]:
        reasons_amber.append("Belum siap transaksi: " + ", ".join(b["code"] for b in readiness["blocks"]))
    if events["stuck_pending"]:
        reasons_amber.append(f"{events['stuck_pending']} event tertahan > 10 menit")
    if not onboarding_completed:
        reasons_amber.append("Pengaturan awal belum selesai")
    if reasons_red:
        return "red", reasons_red + reasons_amber
    if reasons_amber:
        return "amber", reasons_amber
    return "green", []


def shop_health(org, *, now=None):
    from apps.accounting.services.readiness import check_organization_readiness

    now = now or timezone.now()
    readiness = check_organization_readiness(org)
    books = _books(org)
    events = _events(org, now)
    status, reasons = _status(org.onboarding_completed, readiness, books, events)
    return {
        "id": org.id,
        "name": org.name,
        "invoice_code": org.invoice_code,
        "plan": org.plan,
        "is_active": org.is_active,
        "created_at": org.created_at,
        "onboarding_completed": org.onboarding_completed,
        "logins": OrganizationMembership.objects.filter(organization=org, is_active=True).count(),
        "activity": _activity(org, now),
        "books": books,
        "readiness": {
            "ready": readiness["ready"],
            "blocks": [b["code"] for b in readiness["blocks"]],
            "warnings": [w["code"] for w in readiness["warnings"]],
        },
        "events": events,
        "status": status,
        "reasons": reasons,
    }


STATUS_ORDER = {"red": 0, "amber": 1, "green": 2}


def platform_overview(*, now=None):
    now = now or timezone.now()
    shops = [shop_health(org, now=now) for org in Organization.objects.all()]

    def sort_key(s):
        # Problems first; within a colour, the most recently active shop first.
        last = s["activity"]["last_activity_at"] or s["created_at"]
        return (STATUS_ORDER[s["status"]], -last.timestamp() if last else 0)

    shops.sort(key=sort_key)
    week = now - timedelta(days=7)
    return {
        "generated_at": now,
        "totals": {
            "shops": len(shops),
            "active_last_7_days": sum(
                1 for s in shops if s["activity"]["last_activity_at"] and s["activity"]["last_activity_at"] >= week
            ),
            "red": sum(1 for s in shops if s["status"] == "red"),
            "amber": sum(1 for s in shops if s["status"] == "amber"),
            "green": sum(1 for s in shops if s["status"] == "green"),
        },
        "shops": shops,
    }
