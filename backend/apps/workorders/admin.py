from django.contrib import admin

from .models import WorkOrder, WorkOrderJobLine, WorkOrderMaterialLine, WorkOrderSequence


class WorkOrderJobLineInline(admin.TabularInline):
    model = WorkOrderJobLine
    extra = 0


class WorkOrderMaterialLineInline(admin.TabularInline):
    model = WorkOrderMaterialLine
    extra = 0
    readonly_fields = ("part", "quantity", "unit_price_at_time")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display  = ("number", "vehicle", "status", "received_by", "created_at")
    list_filter   = ("status",)
    search_fields = ("number", "vehicle__plate_number")
    inlines       = [WorkOrderJobLineInline, WorkOrderMaterialLineInline]
    readonly_fields = ("number", "sequence_number", "service_record", "created_at", "updated_at")


@admin.register(WorkOrderSequence)
class WorkOrderSequenceAdmin(admin.ModelAdmin):
    list_display = ("organization", "last_sequence")
