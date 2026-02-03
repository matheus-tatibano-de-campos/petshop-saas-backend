from django.contrib import admin

from .models import Customer, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["subdomain", "name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["subdomain", "name"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "cpf", "email", "tenant", "created_at"]
    search_fields = ["name", "cpf", "email"]
