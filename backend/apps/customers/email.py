# =============================================================================
# === backend/apps/customers/email.py ===
# =============================================================================
"""
Fase 2.5 — real magic-link delivery via Resend (confirmed with Chris,
3 Aug — Resend over SendGrid; no API key or verified sending domain
configured yet at the time this was written).

Own module, not inlined into views.py — same "a real send is a real,
independently testable side effect" reasoning already established for
apps.estimates.pdf and apps.workorders.pdf.

Deliberately fails soft, never raises: a broken email provider (no
key yet, a bad key, a Resend outage, no network) must never 500 the
magic-link request endpoint, and must never let the caller behave
differently depending on whether the send worked — that would leak
information about whether an email is a real registered customer,
exactly the security property CustomerMagicLinkRequestView already
guards (same generic "if registered, sent" response regardless).

Requires the `resend` package — not yet in requirements/base.txt,
add manually:
    resend

And three new settings — not yet in config/settings/base.py, add:
    RESEND_API_KEY = config("RESEND_API_KEY", default="")
    CUSTOMER_MAGIC_LINK_FROM_EMAIL = config("CUSTOMER_MAGIC_LINK_FROM_EMAIL", default="noreply@arthasee.com")
    FRONTEND_BASE_URL = config("FRONTEND_BASE_URL", default="http://localhost:3000")

Until RESEND_API_KEY is actually set, this module does nothing but
log a warning — completely safe to ship and deploy right now. The
moment a real key + verified domain exist, real emails start going
out with zero further code changes.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_magic_link_email(customer, token):
    """
    Returns True if a real send was attempted and Resend accepted it,
    False otherwise (not yet configured, or a real send failure).
    Callers should treat False purely as an internal signal for
    logging/monitoring — never surface it to the requester, see this
    module's own docstring for why.
    """
    api_key = getattr(settings, "RESEND_API_KEY", "")
    if not api_key:
        # Expected right now — Chris's own confirmation, 3 Aug: no
        # API key/domain set up yet. A real, known, temporary state,
        # not an error — logged so it's visible in server logs
        # without breaking the request itself.
        logger.warning("RESEND_API_KEY not configured — magic link email not sent to %s", customer.email)
        return False

    # Imported here, not at module level, deliberately — so this
    # whole module stays importable (and every other test in this
    # file keeps working) even before `resend` is added to
    # requirements/base.txt. Only actually needed once a send is for
    # real attempted, i.e. once an API key genuinely exists.
    import resend
    resend.api_key = api_key

    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000")
    from_address = getattr(settings, "CUSTOMER_MAGIC_LINK_FROM_EMAIL", "noreply@arthasee.com")
    magic_link_url = f"{frontend_base}/customer/verify?token={token}"
    org_name = customer.organization.name

    try:
        resend.Emails.send({
            "from": from_address,
            "to": [customer.email],
            "subject": f"Link Masuk — {org_name}",
            "html": _build_email_html(customer, org_name, magic_link_url),
        })
        return True
    except Exception:
        # Deliberately broad — a provider-side failure (bad key,
        # outage, rate limit, network) must never bubble up into a
        # 500 on the request endpoint. Logged with the real traceback
        # for whoever's debugging; swallowed for the caller.
        logger.exception("Failed to send magic link email to %s", customer.email)
        return False


def _build_email_html(customer, org_name, magic_link_url):
    """
    Plain, honest HTML — no external images/fonts to keep this
    resilient across email clients, matching the same "no new
    deployment risk" philosophy already behind other document-
    generation choices in this project (e.g. xhtml2pdf over
    WeasyPrint). Standard magic-link disclaimer included
    ("if you didn't request this, ignore it") — real security
    hygiene, not boilerplate.
    """
    return f"""
    <div style="font-family: Helvetica, Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #17181a;">
        <h2 style="margin-bottom: 4px;">{org_name}</h2>
        <p style="color: #6b6b6b; margin-top: 0;">Link Masuk ke Akun Anda</p>
        <p>Halo {customer.name},</p>
        <p>Klik tombol di bawah untuk masuk ke akun Anda dan melihat status servis kendaraan Anda:</p>
        <p style="margin: 24px 0;">
            <a href="{magic_link_url}" style="background: #b5502f; color: #ffffff; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-block;">
                Masuk ke Akun Saya
            </a>
        </p>
        <p style="color: #6b6b6b; font-size: 13px;">Link ini berlaku selama 15 menit dan hanya bisa digunakan satu kali.</p>
        <p style="color: #6b6b6b; font-size: 13px;">Jika Anda tidak meminta link ini, abaikan email ini.</p>
    </div>
    """
