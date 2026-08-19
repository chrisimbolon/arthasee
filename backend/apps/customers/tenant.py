# =============================================================================
# === backend/apps/customers/tenant.py ===
# =============================================================================
"""
Resolves which Organization the customer-facing portal belongs to.

Single deployment per shop, for now — confirmed with Chris directly.
A plain settings value, NOT real domain/Host-header parsing — that
infrastructure doesn't exist anywhere in this codebase yet (no Site
model, no custom_domain field on Organization, nothing).

Deliberately kept as its own tiny, isolated function rather than
inlined into whichever view needs it — this is the ONE place that
needs to change when real subdomain-based multi-tenant resolution
gets built later. Nothing calling get_customer_portal_organization()
needs to know or care how the org actually gets resolved.
"""
from django.conf import settings

from apps.organizations.models import Organization


def get_customer_portal_organization():
    """
    Returns the real Organization this deployment's customer portal
    belongs to, or None if CUSTOMER_PORTAL_ORGANIZATION_ID isn't
    configured (or points at an org that doesn't exist) — callers
    must treat None as a real, visible server misconfiguration, not
    silently proceed as if a valid org was found.
    """
    org_id = getattr(settings, "CUSTOMER_PORTAL_ORGANIZATION_ID", "")
    if not org_id:
        return None
    return Organization.objects.filter(id=org_id).first()
