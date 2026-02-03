from django.contrib import admin

from .models import Customer, Pet, Service, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["subdomain", "name", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["subdomain", "name"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "cpf", "email", "tenant", "created_at"]
    search_fields = ["name", "cpf", "email"]


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = ["name", "species", "breed", "customer", "tenant"]
    list_filter = ["species"]
    search_fields = ["name", "breed"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "price", "duration_minutes", "is_active", "tenant"]
    list_filter = ["is_active"]
    search_fields = ["name"]
