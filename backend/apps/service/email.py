# =============================================================================
# === backend/apps/service/email.py ===
# =============================================================================
"""
Service reminder email delivery via Resend — same provider, same
"fails soft, never raises" philosophy as
apps.customers.email.send_magic_link_email, which this mirrors
directly. A failed send here must never crash the whole daily
reminder run — one bad address shouldn't stop every other real
customer from getting reminded that day.

Reuses the SAME RESEND_API_KEY setting already configured for the
customer magic-link flow — same provider account, no new key needed.
One new setting only:
    SERVICE_REMINDER_FROM_EMAIL = config("SERVICE_REMINDER_FROM_EMAIL", default="noreply@arthasee.com")

Until RESEND_API_KEY is set, this does nothing but log a warning —
same safe-to-ship-right-now behavior as the magic-link module.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_service_reminder_email(vehicle):
    """
    Returns True if a real send was attempted and Resend accepted
    it, False otherwise. The caller (send_service_reminders
    management command) uses this return value directly to decide
    whether to log SENT or FAILED in ServiceReminderLog.
    """
    customer = vehicle.customer
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        # Same real, known, temporary state as the magic-link
        # module — not an error, just not configured yet.
        logger.warning(
            "RESEND_API_KEY not configured — service reminder not sent for vehicle %s",
            vehicle.plate_number,
        )
        return False

    # Imported here, not at module level — same reasoning as
    # apps.customers.email: keeps this module importable even before
    # `resend` is in requirements/base.txt, only needed once a send
    # is for real attempted.
    import resend
    resend.api_key = api_key

    from_address = getattr(settings, "SERVICE_REMINDER_FROM_EMAIL", "noreply@arthasee.com")
    org_name = vehicle.organization.name

    try:
        resend.Emails.send({
            "from": from_address,
            "to": [customer.email],
            "subject": f"Waktunya Servis Berkala — {vehicle.plate_number}",
            "html": _build_reminder_html(vehicle, customer, org_name),
        })
        return True
    except Exception:
        # Deliberately broad — same reasoning as the magic-link
        # module: a provider-side failure must never crash the
        # whole daily run over one bad address.
        logger.exception(
            "Failed to send service reminder email for vehicle %s", vehicle.plate_number,
        )
        return False


def _build_reminder_html(vehicle, customer, org_name):
    """
    Same plain, no-external-asset HTML philosophy as
    apps.customers.email._build_email_html — resilient across email
    clients, no new deployment risk.
    """
    last_service = vehicle.last_service_date.strftime("%d %B %Y") if vehicle.last_service_date else "-"
    return f"""
    <div style="font-family: Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #17181a;">
        <h2 style="margin-bottom: 4px;">{org_name}</h2>
        <p style="color: #6b6b6b; margin-top: 0;">Pengingat Servis Berkala</p>
        <p>Halo {customer.name},</p>
        <p>
            Kendaraan Anda ({vehicle.plate_number} — {vehicle.model}) terakhir
            diservis pada {last_service}. Sudah waktunya untuk servis berkala
            berikutnya.
        </p>
        <p>Silakan hubungi kami untuk membuat janji servis.</p>
        <p style="color: #6b6b6b; font-size: 13px;">Email ini dikirim otomatis berdasarkan riwayat servis kendaraan Anda di {org_name}.</p>
    </div>
    """
