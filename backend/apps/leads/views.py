# =============================================================================
# === backend/apps/leads/views.py ===
# =============================================================================
from rest_framework import status
from rest_framework.response import Response

from apps.core.views import TenantScopedAPIView

from .models import RejectedQuote
from .serializers import RejectedQuoteSerializer


class RejectedQuoteListView(TenantScopedAPIView):
    """
    GET/POST /api/leads/rejected-quotes/
    ?follow_up_status=PENDING — this IS Made's personal call-list
    mechanism: no separate feature needed, just a filter on the one
    field that tracks where he is in following up with someone.
    ?reason= — supports the lightweight side of "aggregate pricing
    insights" (count how many came back for a given filter) without
    building a dedicated analytics view before there's enough real
    volume for one to mean anything.
    """
    model = RejectedQuote

    def get(self, request):
        quotes = self.get_queryset().order_by("-created_at")
        follow_up_status = request.query_params.get("follow_up_status")
        if follow_up_status:
            quotes = quotes.filter(follow_up_status=follow_up_status)
        reason = request.query_params.get("reason")
        if reason:
            quotes = quotes.filter(reason=reason)
        serializer = RejectedQuoteSerializer(quotes, many=True)
        return Response({"success": True, "count": quotes.count(), "results": serializer.data})

    def post(self, request):
        org = self._resolve_org(request)
        if org is None:
            return Response(
                {"success": False, "message": "Anda belum tergabung dalam bengkel manapun."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = RejectedQuoteSerializer(data=request.data)
        if serializer.is_valid():
            quote = serializer.save(organization=org, created_by=request.user)
            return Response(
                {"success": True, "rejected_quote": RejectedQuoteSerializer(quote).data},
                status=status.HTTP_201_CREATED,
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def _resolve_org(self, request):
        membership = request.user.memberships.filter(is_active=True).first()
        return membership.organization if membership else None


class RejectedQuoteDetailView(TenantScopedAPIView):
    """
    GET/PUT/DELETE /api/leads/rejected-quotes/<id>/
    Freely editable and deletable — nothing else in the domain
    references a RejectedQuote (Made confirmed manual conversion, no
    auto-linking), so there's no Principle-2-style PROTECT concern
    here the way there is for Customer/Vehicle/Part.
    """
    model = RejectedQuote

    def get(self, request, pk):
        quote = self.get_object(pk)
        return Response({"success": True, "rejected_quote": RejectedQuoteSerializer(quote).data})

    def put(self, request, pk):
        quote = self.get_object(pk)
        serializer = RejectedQuoteSerializer(quote, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "rejected_quote": RejectedQuoteSerializer(quote).data})
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        quote = self.get_object(pk)
        quote.delete()
        return Response({"success": True, "message": "Data berhasil dihapus."})
