# =============================================================================
# === backend/apps/service/management/commands/send_service_reminders.py ===
# =============================================================================
"""
Made's own rule, his own words: "Cara paling sederhana untuk
mengingatkan ke pelanggan untuk kembali lagi ke service berkala
adalah dengan mengirimkan pesan 3 s/d 4 bulan sejak service
terakhir." Meant to run once a day via cron — same real pattern
already proven on the production droplet's own crontab
(snapshot_risk_daily, mark_overdue_payments): a plain management
command, invoked through `docker exec` once a deployed container
exists. No Celery, no broker, no new infrastructure.

Deliberately covers every organization in one run, not scoped to a
single tenant — this runs unattended with no request/session to
scope it from, same as any other cron-driven job would need.

A vehicle with no customer email never gets sent to, but is never
silently dropped either — it's logged as needing a manual follow-up,
same "don't hide an honest gap" discipline already used elsewhere in
this project (the P&L's gross_profit_note, the trend chart's
projected_months_used caveat).
"""
from django.core.management.base import BaseCommand

from apps.service.email import send_service_reminder_email
from apps.service.models import ServiceReminderLog, Vehicle


class Command(BaseCommand):
    help = "Send service reminder emails to customers due for their 3-4 month check-in."

    def handle(self, *args, **options):
        due_vehicles = [
            v for v in Vehicle.objects.select_related("customer", "organization").all()
            if v.is_due_for_service_reminder
        ]

        sent_count = 0
        failed_count = 0
        no_email_count = 0
        already_logged_count = 0

        for vehicle in due_vehicles:
            already_logged = ServiceReminderLog.objects.filter(
                vehicle=vehicle, for_last_service_date=vehicle.last_service_date,
            ).exists()
            if already_logged:
                already_logged_count += 1
                continue

            if not vehicle.customer.email:
                no_email_count += 1
                self.stdout.write(self.style.WARNING(
                    f"No email on file — {vehicle.plate_number} ({vehicle.customer.name}), "
                    f"needs manual follow-up."
                ))
                continue

            success = send_service_reminder_email(vehicle)
            ServiceReminderLog.objects.create(
                organization=vehicle.organization,
                vehicle=vehicle,
                for_last_service_date=vehicle.last_service_date,
                status="SENT" if success else "FAILED",
            )
            if success:
                sent_count += 1
                self.stdout.write(self.style.SUCCESS(f"Sent — {vehicle.plate_number} ({vehicle.customer.email})"))
            else:
                failed_count += 1
                self.stdout.write(self.style.ERROR(f"Failed — {vehicle.plate_number} ({vehicle.customer.email})"))

        self.stdout.write(self.style.SUCCESS(
            f"Done. Sent: {sent_count}, Failed: {failed_count}, "
            f"No email (manual follow-up needed): {no_email_count}, "
            f"Already reminded this window: {already_logged_count}"
        ))
