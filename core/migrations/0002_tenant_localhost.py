from django.db import migrations


def create_localhost_tenant(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")
    if not Tenant.objects.filter(subdomain="localhost").exists():
        Tenant.objects.create(subdomain="localhost", name="Local Dev", is_active=True)


def reverse(apps, schema_editor):
    Tenant = apps.get_model("core", "Tenant")
    Tenant.objects.filter(subdomain="localhost").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [migrations.RunPython(create_localhost_tenant, reverse)]
