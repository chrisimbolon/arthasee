from django.contrib import admin

from .models import Organization, OrganizationMembership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "is_active", "created_at")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display  = ("user", "organization", "role", "is_active")
    list_filter   = ("role", "is_active")
