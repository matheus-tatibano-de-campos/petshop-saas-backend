from django.test import Client, TestCase

from .models import Tenant


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
