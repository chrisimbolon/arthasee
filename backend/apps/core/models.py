# =============================================================================
# === backend/apps/core/models.py
# =============================================================================
"""
Arthasee — Core

Same tenant-scoping pattern proven across every DevelopIndo sprint:
one abstract base every real model inherits from, one hook point for
models that derive their org from a relation instead of expecting
the caller to set it explicitly.
"""
from django.db import models


class TenantScopedModel(models.Model):
    """
    Abstract base for every model that belongs to exactly one
    Organization. Paired with TenantScopedAPIView (see views.py) —
    together they're the only two places tenant isolation actually
    gets enforced, which is deliberate: one mechanism, reused
    everywhere, rather than each view reinventing its own scoping.

    _resolve_organization() is the override point for models that
    derive their organization from a related object rather than
    being set explicitly by the caller — e.g. a ServiceRecord derives
    its org from its own Vehicle, the same way DevelopIndo's
    CommissionTier derived its org from its own CommissionPolicy.
    """
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE,
    )

    class Meta:
        abstract = True

    def _resolve_organization(self):
        return None

    def save(self, *args, **kwargs):
        if self.organization_id is None:
            resolved = self._resolve_organization()
            if resolved is not None:
                self.organization = resolved
        super().save(*args, **kwargs)
