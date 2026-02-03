from decimal import Decimal

from django.db import migrations


def create_test_services(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")
    Service = apps.get_model("core", "Service")
    tenant = Tenant.objects.filter(subdomain="localhost").first()
    if not tenant:
        return
    services = [
        {"name": "Banho", "description": "Banho completo", "price": Decimal("50.00"), "duration_minutes": 60},
        {"name": "Tosa", "description": "Tosa higiênica ou completa", "price": Decimal("80.00"), "duration_minutes": 90},
        {"name": "Consulta veterinária", "description": "Consulta de rotina", "price": Decimal("120.00"), "duration_minutes": 30},
    ]
    for s in services:
        Service.objects.get_or_create(tenant=tenant, name=s["name"], defaults=s)


def reverse(apps, schema_editor):
    Service = apps.get_model("core", "Service")
    Tenant = apps.get_model("core", "Tenant")
    tenant = Tenant.objects.filter(subdomain="localhost").first()
    if tenant:
        Service.objects.filter(tenant=tenant, name__in=["Banho", "Tosa", "Consulta veterinária"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0005_add_service_model")]

    operations = [migrations.RunPython(create_test_services, reverse)]
