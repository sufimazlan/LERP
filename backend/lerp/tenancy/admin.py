from django.contrib import admin

from lerp.tenancy.models import Membership, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "status", "ai_mode", "ai_monthly_budget_myr", "ledger_adapter"]
    search_fields = ["slug", "name"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant", "is_active"]
    list_filter = ["is_active", "tenant"]
