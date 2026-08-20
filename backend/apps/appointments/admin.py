from django.contrib import admin

from .models import Appointment, AppointmentDayLock

admin.site.register(Appointment)
admin.site.register(AppointmentDayLock)
