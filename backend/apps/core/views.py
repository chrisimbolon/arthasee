# =============================================================================
# === backend/apps/core/views.py ===
# =============================================================================
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView


class TenantScopedAPIView(APIView):
    """
    Every view touching a TenantScopedModel extends this instead of
    writing its own filtering — one mechanism, reused everywhere,
    same discipline DevelopIndo used from its very first sprint.

    super_admin sees everything (platform-level access, not tied to
    any one shop's membership). Everyone else only ever sees rows
    belonging to an organization they're an active member of.
    """
    model = None

    def get_queryset(self):
        user = self.request.user
        if user.role == "super_admin":
            return self.model.objects.all()
        org_ids = user.memberships.filter(
            is_active=True
        ).values_list("organization_id", flat=True)
        return self.model.objects.filter(organization_id__in=org_ids)

    def get_object(self, pk):
        try:
            return self.get_queryset().get(pk=pk)
        except self.model.DoesNotExist:
            raise NotFound("Data tidak ditemukan.")
