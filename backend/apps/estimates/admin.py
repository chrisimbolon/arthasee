from django.contrib import admin

from .models import Estimate, EstimateLineItem, EstimateSequence


class EstimateLineItemInline(admin.TabularInline):
    model = EstimateLineItem
    extra = 0


@admin.register(Estimate)
class EstimateAdmin(admin.ModelAdmin):
    list_display  = ("number", "vehicle", "status", "created_at")
    list_filter   = ("status",)
    search_fields = ("number", "vehicle__plate_number")
    inlines       = [EstimateLineItemInline]
    readonly_fields = ("number", "sequence_number", "work_order", "created_at", "updated_at")


@admin.register(EstimateSequence)
class EstimateSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")
