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

    def get_organization(self):
        """
        Resolves the acting Organization for the current request —
        for creating a resource with no parent object to derive org
        from (Supplier, GoodsReceivedNote, SupplierInvoice — none of
        them inherit organization from an existing relation the way
        Invoice derives it from service_record). Same membership-
        lookup idiom apps.organizations.views.MyOrganizationView.get()
        already uses inline — one real implementation now, not
        several copies across every view that needs it.

        super_admin has no single "their" organization by definition
        (platform-level access spans every org) — returns None for
        that role too, same as an ordinary user with no active
        membership. Callers must handle None explicitly; there is no
        organization to silently default to for a super_admin
        creating a new tenant-scoped document.
        """
        if self.request.user.role == "super_admin":
            return None
        membership = self.request.user.memberships.filter(
            is_active=True
        ).select_related("organization").first()
        return membership.organization if membership else None
