from django.contrib import admin

from .models import Customer, ServiceRecord, Vehicle


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display  = ("name", "phone", "stnk_name", "organization")
    search_fields = ("name", "phone", "stnk_name")


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display  = ("plate_number", "model", "customer", "current_odometer_km", "last_service_date")
    search_fields = ("plate_number", "model")
    list_filter   = ("vehicle_type",)


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display  = ("vehicle", "service_date", "odometer_km")
    list_filter   = ("service_date",)
