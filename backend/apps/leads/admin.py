from django.contrib import admin

from .models import RejectedQuote


@admin.register(RejectedQuote)
class RejectedQuoteAdmin(admin.ModelAdmin):
    list_display  = ("name", "phone", "reason", "follow_up_status", "quoted_amount", "created_at")
    list_filter   = ("reason", "follow_up_status")
    search_fields = ("name", "phone", "vehicle_description")
