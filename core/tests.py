from django.db import models
from django.test import Client, TestCase

from .context import clear_current_tenant, get_current_tenant, set_current_tenant
from .models import Tenant, TenantAwareModel


class TenantMiddlewareIntegrationTests(TestCase):
    """Integration tests for TenantMiddleware - DoD: subdomain isolation + error format."""

    def setUp(self):
        self.client = Client()
        self.tenant1 = Tenant.objects.create(
            subdomain="tenant1", name="Tenant 1", is_active=True
        )
        self.tenant2 = Tenant.objects.create(
            subdomain="tenant2", name="Tenant 2", is_active=True
        )

    def test_tenant_not_found_returns_404_with_standard_error_format(self):
        """Unknown subdomain returns 404 with consistent error format."""
        response = self.client.get("/api/health/", HTTP_HOST="unknown.localhost:8000")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data["error"]["code"], "TENANT_NOT_FOUND")
        self.assertEqual(data["error"]["message"], "Tenant não encontrado")

    def test_localhost_resolves_to_localhost_tenant(self):
        """127.0.0.1 and localhost resolve to 'localhost' subdomain."""
        for host in ("localhost:8000", "127.0.0.1:8000"):
            with self.subTest(host=host):
                response = self.client.get("/api/tenant-info/", HTTP_HOST=host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["subdomain"], "localhost")

    def test_subdomain_isolation_different_tenants_per_host(self):
        """Requests with different subdomains receive different tenants."""
        r1 = self.client.get("/api/tenant-info/", HTTP_HOST="tenant1.localhost:8000")
        r2 = self.client.get("/api/tenant-info/", HTTP_HOST="tenant2.localhost:8000")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(r1.json()["tenant_id"], r2.json()["tenant_id"])
        self.assertEqual(r1.json()["subdomain"], "tenant1")
        self.assertEqual(r2.json()["subdomain"], "tenant2")

    def test_inactive_tenant_returns_404(self):
        """Inactive tenant returns 404."""
        self.tenant1.is_active = False
        self.tenant1.save()
        response = self.client.get("/api/health/", HTTP_HOST="tenant1.localhost:8000")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "TENANT_NOT_FOUND")


class TestModel(TenantAwareModel):
    """Test model for TenantAwareModel unit tests."""

    name = models.CharField(max_length=100)

    class Meta:
        app_label = "core"


class TenantAwareModelUnitTests(TestCase):
    """Unit tests for TenantAwareModel - DoD: auto-tenant, manager filtering."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create the TestModel table dynamically for tests
        from django.db import connection
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(TestModel)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        # Drop the TestModel table after tests (if it still exists)
        from django.db import connection
        try:
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(TestModel)
        except Exception:
            pass  # Table might already be deleted by test db teardown

    def setUp(self):
        self.tenant1 = Tenant.objects.create(
            subdomain="test1", name="Test Tenant 1", is_active=True
        )
        self.tenant2 = Tenant.objects.create(
            subdomain="test2", name="Test Tenant 2", is_active=True
        )

    def tearDown(self):
        clear_current_tenant()

    def test_save_auto_sets_tenant_from_context(self):
        """save() auto-sets tenant from thread-local context."""
        set_current_tenant(self.tenant1)
        obj = TestModel(name="Test Object")
        obj.save()
        self.assertEqual(obj.tenant, self.tenant1)

    def test_save_raises_error_when_no_tenant_in_context(self):
        """save() raises ValueError when no tenant in context and tenant not set."""
        clear_current_tenant()
        obj = TestModel(name="Test Object")
        with self.assertRaisesMessage(
            ValueError, "Tenant required. Set tenant or ensure TenantMiddleware has run."
        ):
            obj.save()

    def test_save_respects_explicit_tenant(self):
        """save() respects explicitly set tenant, doesn't override."""
        set_current_tenant(self.tenant1)
        obj = TestModel(name="Test Object", tenant=self.tenant2)
        obj.save()
        self.assertEqual(obj.tenant, self.tenant2)

    def test_manager_filters_by_current_tenant(self):
        """Manager filters queryset by current tenant."""
        set_current_tenant(self.tenant1)
        obj1 = TestModel.objects.create(name="Object 1")
        
        set_current_tenant(self.tenant2)
        obj2 = TestModel.objects.create(name="Object 2")

        set_current_tenant(self.tenant1)
        qs = TestModel.objects.all()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().id, obj1.id)

        set_current_tenant(self.tenant2)
        qs = TestModel.objects.all()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().id, obj2.id)

    def test_manager_returns_none_when_no_tenant_in_context(self):
        """Manager returns empty queryset when no tenant in context."""
        set_current_tenant(self.tenant1)
        TestModel.objects.create(name="Object 1")

        clear_current_tenant()
        qs = TestModel.objects.all()
        self.assertEqual(qs.count(), 0)
