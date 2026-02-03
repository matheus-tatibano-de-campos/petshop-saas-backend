import jwt
from django.conf import settings
from django.db import models
from django.test import Client, TestCase
from rest_framework.test import APIClient, APIRequestFactory

from .context import clear_current_tenant, get_current_tenant, set_current_tenant
from .models import Customer, Tenant, TenantAwareModel, User
from .permissions import IsOwner, IsOwnerOrAttendant


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


class JWTAuthenticationTests(TestCase):
    """Tests for JWT authentication - DoD: login returns tokens, tenant_id in payload."""

    def setUp(self):
        self.client = Client()
        self.tenant, _ = Tenant.objects.get_or_create(
            subdomain="localhost",
            defaults={"name": "Local Dev", "is_active": True},
        )
        self.user = User.objects.create_user(
            email="owner@petshop.com",
            password="testpass123",
            role="OWNER",
            tenant=self.tenant,
        )

    def test_login_returns_access_and_refresh_tokens(self):
        """POST /auth/login returns access and refresh tokens."""
        response = self.client.post(
            "/api/auth/login/",
            {"email": "owner@petshop.com", "password": "testpass123"},
            content_type="application/json",
            HTTP_HOST="localhost:8000",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertIn("refresh", data)

    def test_login_with_invalid_credentials_returns_401(self):
        """POST /auth/login with wrong password returns 401."""
        response = self.client.post(
            "/api/auth/login/",
            {"email": "owner@petshop.com", "password": "wrongpass"},
            content_type="application/json",
            HTTP_HOST="localhost:8000",
        )
        self.assertEqual(response.status_code, 401)

    def test_access_token_contains_tenant_id(self):
        """Access token payload contains tenant_id."""
        response = self.client.post(
            "/api/auth/login/",
            {"email": "owner@petshop.com", "password": "testpass123"},
            content_type="application/json",
            HTTP_HOST="localhost:8000",
        )
        access_token = response.json()["access"]
        payload = jwt.decode(
            access_token,
            settings.SIMPLE_JWT["SIGNING_KEY"],
            algorithms=[settings.SIMPLE_JWT["ALGORITHM"]],
        )
        self.assertEqual(payload["tenant_id"], self.tenant.id)
        self.assertEqual(payload["role"], "OWNER")
        self.assertEqual(payload["email"], "owner@petshop.com")

    def test_refresh_token_returns_new_access_token(self):
        """POST /auth/refresh returns new access token."""
        login_response = self.client.post(
            "/api/auth/login/",
            {"email": "owner@petshop.com", "password": "testpass123"},
            content_type="application/json",
            HTTP_HOST="localhost:8000",
        )
        refresh_token = login_response.json()["refresh"]

        refresh_response = self.client.post(
            "/api/auth/refresh/",
            {"refresh": refresh_token},
            content_type="application/json",
            HTTP_HOST="localhost:8000",
        )
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("access", refresh_response.json())


class PermissionClassesTests(TestCase):
    """Unit tests for IsOwner and IsOwnerOrAttendant permissions."""

    def setUp(self):
        self.factory = APIRequestFactory()
        tenant = Tenant.objects.create(subdomain="permtenant", name="Tenant Perm")
        self.owner = User.objects.create_user(
            email="owner@test.com", password="pass123", role="OWNER", tenant=tenant
        )
        self.attendant = User.objects.create_user(
            email="att@test.com", password="pass123", role="ATTENDANT", tenant=tenant
        )
        self.superuser = User.objects.create_superuser(
            email="super@test.com", password="pass123", tenant=tenant
        )

    def test_is_owner_allows_owner_and_superuser(self):
        request = self.factory.get("/dummy")
        request.user = self.owner
        self.assertTrue(IsOwner().has_permission(request, None))

        request.user = self.superuser
        self.assertTrue(IsOwner().has_permission(request, None))

        request.user = self.attendant
        self.assertFalse(IsOwner().has_permission(request, None))

    def test_is_owner_or_attendant_allows_roles(self):
        request = self.factory.get("/dummy")
        request.user = self.owner
        self.assertTrue(IsOwnerOrAttendant().has_permission(request, None))

        request.user = self.attendant
        self.assertTrue(IsOwnerOrAttendant().has_permission(request, None))

        request.user = self.superuser
        self.assertTrue(IsOwnerOrAttendant().has_permission(request, None))

        request.user = None
        self.assertFalse(IsOwnerOrAttendant().has_permission(request, None))


class TenantCreateViewTests(TestCase):
    """Integration tests ensuring only superuser can create tenants via API."""

    def setUp(self):
        self.client = APIClient()
        self.superuser = User.objects.create_superuser(
            email="super@admin.com", password="pass123"
        )
        tenant = Tenant.objects.create(subdomain="tenantcreatetest", name="T1")
        self.owner = User.objects.create_user(
            email="owner@tenant.com", password="pass123", role="OWNER", tenant=tenant
        )

    def test_superuser_can_create_tenant(self):
        self.client.force_authenticate(user=self.superuser)
        response = self.client.post(
            "/api/tenants/",
            {"name": "New Tenant", "subdomain": "newtenant", "is_active": True},
            format="json",
            HTTP_HOST="localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["subdomain"], "newtenant")

    def test_owner_cannot_create_tenant(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/tenants/",
            {"name": "Another Tenant", "subdomain": "anothertenant"},
            format="json",
            HTTP_HOST="localhost:8000",
        )
        self.assertEqual(response.status_code, 403)


class CustomerAPITests(TestCase):
    """Integration tests for Customer CRUD."""

    valid_cpf = "39053344705"

    def setUp(self):
        self.client = APIClient()
        self.tenant1 = Tenant.objects.create(subdomain="cust1", name="Tenant 1")
        self.tenant2 = Tenant.objects.create(subdomain="cust2", name="Tenant 2")
        self.owner1 = User.objects.create_user(
            email="owner1@tenant.com", password="pass123", role="OWNER", tenant=self.tenant1
        )
        self.owner2 = User.objects.create_user(
            email="owner2@tenant.com", password="pass123", role="OWNER", tenant=self.tenant2
        )

    def test_create_customer_with_valid_cpf(self):
        self.client.force_authenticate(user=self.owner1)
        response = self.client.post(
            "/api/customers/",
            {"name": "João", "cpf": self.valid_cpf, "email": "joao@example.com", "phone": "11999999999"},
            format="json",
            HTTP_HOST="cust1.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["cpf"], self.valid_cpf)
        self.assertEqual(Customer.all_objects.count(), 1)

    def test_create_customer_with_invalid_cpf_returns_400(self):
        self.client.force_authenticate(user=self.owner1)
        response = self.client.post(
            "/api/customers/",
            {"name": "Maria", "cpf": "12345678900", "email": "maria@example.com", "phone": "11888888888"},
            format="json",
            HTTP_HOST="cust1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cpf", response.data)

    def test_duplicate_cpf_same_tenant_returns_400(self):
        self.client.force_authenticate(user=self.owner1)
        payload = {"name": "João", "cpf": self.valid_cpf, "email": "joao@example.com", "phone": "11999999999"}
        self.client.post("/api/customers/", payload, format="json", HTTP_HOST="cust1.localhost:8000")
        response = self.client.post("/api/customers/", payload, format="json", HTTP_HOST="cust1.localhost:8000")
        self.assertEqual(response.status_code, 400)
        self.assertIn("cpf", response.data)

    def test_duplicate_cpf_different_tenants_allowed(self):
        self.client.force_authenticate(user=self.owner1)
        payload = {"name": "João", "cpf": self.valid_cpf, "email": "joao@example.com", "phone": "11999999999"}
        self.client.post("/api/customers/", payload, format="json", HTTP_HOST="cust1.localhost:8000")

        self.client.force_authenticate(user=self.owner2)
        response = self.client.post(
            "/api/customers/",
            payload,
            format="json",
            HTTP_HOST="cust2.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Customer.all_objects.count(), 2)

    def test_list_returns_only_current_tenant_customers(self):
        self.client.force_authenticate(user=self.owner1)
        self.client.post(
            "/api/customers/",
            {"name": "João", "cpf": self.valid_cpf, "email": "joao@example.com", "phone": "11999999999"},
            format="json",
            HTTP_HOST="cust1.localhost:8000",
        )
        self.client.force_authenticate(user=self.owner2)
        self.client.post(
            "/api/customers/",
            {"name": "Maria", "cpf": "52998224725", "email": "maria@example.com", "phone": "11888888888"},
            format="json",
            HTTP_HOST="cust2.localhost:8000",
        )

        self.client.force_authenticate(user=self.owner1)
        response = self.client.get("/api/customers/", HTTP_HOST="cust1.localhost:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "João")
