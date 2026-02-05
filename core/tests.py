from datetime import timedelta

from decimal import Decimal
from unittest.mock import MagicMock, patch

import jwt
from django.conf import settings
from django.db import models
from django.test import Client, TestCase
from rest_framework.test import APIClient, APIRequestFactory

from .context import clear_current_tenant, get_current_tenant, set_current_tenant
from .models import Appointment, Customer, Payment, Pet, Service, Tenant, TenantAwareModel, User
from .permissions import IsOwner, IsOwnerOrAttendant
from .services import AppointmentService, InvalidTransitionError


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

    def test_create_customer_with_invalid_cpf_returns_400_standard_format(self):
        self.client.force_authenticate(user=self.owner1)
        response = self.client.post(
            "/api/customers/",
            {"name": "Maria", "cpf": "12345678900", "email": "maria@example.com", "phone": "11888888888"},
            format="json",
            HTTP_HOST="cust1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "INVALID_CPF")
        self.assertIn("inválido", response.data["error"]["message"].lower())

    def test_duplicate_cpf_same_tenant_returns_400_standard_format(self):
        self.client.force_authenticate(user=self.owner1)
        payload = {"name": "João", "cpf": self.valid_cpf, "email": "joao@example.com", "phone": "11999999999"}
        self.client.post("/api/customers/", payload, format="json", HTTP_HOST="cust1.localhost:8000")
        response = self.client.post("/api/customers/", payload, format="json", HTTP_HOST="cust1.localhost:8000")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "CPF_DUPLICATE")
        self.assertIn("cadastrado", response.data["error"]["message"].lower())

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


class PetModelTests(TestCase):
    """Tests for Pet model - DoD: cascade delete when customer is removed."""

    def setUp(self):
        self.tenant, _ = Tenant.objects.get_or_create(
            subdomain="localhost", defaults={"name": "Local Dev", "is_active": True}
        )
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="João",
            cpf="39053344705",
            email="joao@example.com",
            phone="11999999999",
        )

    def test_delete_customer_removes_pets(self):
        """Deleting a customer removes associated pets (CASCADE)."""
        set_current_tenant(self.tenant)
        Pet.objects.create(
            name="Rex", species="DOG", breed="Labrador", customer=self.customer
        )
        Pet.objects.create(
            name="Mimi", species="CAT", breed="Siamês", customer=self.customer
        )
        customer_id = self.customer.id
        self.assertEqual(Pet.all_objects.filter(customer_id=customer_id).count(), 2)

        self.customer.delete()
        self.assertEqual(Pet.all_objects.filter(customer_id=customer_id).count(), 0)


class PetAPITests(TestCase):
    """Integration tests for Pet CRUD. DoD: CUSTOMER_WRONG_TENANT, cascade delete."""

    def setUp(self):
        self.client = APIClient()
        self.tenant1 = Tenant.objects.create(subdomain="pet1", name="Tenant 1")
        self.tenant2 = Tenant.objects.create(subdomain="pet2", name="Tenant 2")
        self.owner1 = User.objects.create_user(
            email="owner1@pet.com", password="pass123", role="OWNER", tenant=self.tenant1
        )
        self.owner2 = User.objects.create_user(
            email="owner2@pet.com", password="pass123", role="OWNER", tenant=self.tenant2
        )
        self.cust1 = Customer.all_objects.create(
            tenant=self.tenant1, name="João", cpf="39053344705",
            email="joao@example.com", phone="11999999999",
        )
        self.cust2 = Customer.all_objects.create(
            tenant=self.tenant2, name="Maria", cpf="52998224725",
            email="maria@example.com", phone="11888888888",
        )

    def test_create_pet_success(self):
        """Create pet linked to customer in same tenant."""
        self.client.force_authenticate(user=self.owner1)
        response = self.client.post(
            "/api/pets/",
            {
                "name": "Rex",
                "species": "DOG",
                "breed": "Labrador",
                "birth_date": "2020-01-15",
                "customer": self.cust1.id,
            },
            format="json",
            HTTP_HOST="pet1.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Rex")
        self.assertEqual(response.data["species"], "DOG")
        self.assertEqual(response.data["customer"], self.cust1.id)
        self.assertEqual(Pet.all_objects.count(), 1)

    def test_create_pet_customer_wrong_tenant_returns_400_standard_format(self):
        """Link pet to customer from another tenant -> 400 CUSTOMER_WRONG_TENANT."""
        self.client.force_authenticate(user=self.owner1)
        response = self.client.post(
            "/api/pets/",
            {
                "name": "Rex",
                "species": "DOG",
                "breed": "Labrador",
                "customer": self.cust2.id,
            },
            format="json",
            HTTP_HOST="pet1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "CUSTOMER_WRONG_TENANT")
        self.assertIn("outro tenant", response.data["error"]["message"].lower())
        self.assertEqual(Pet.all_objects.count(), 0)

    def test_update_pet_customer_wrong_tenant_returns_400(self):
        """Update pet to link to customer from another tenant -> 400 CUSTOMER_WRONG_TENANT."""
        set_current_tenant(self.tenant1)
        pet = Pet.objects.create(
            name="Rex", species="DOG", breed="Labrador", customer=self.cust1
        )
        self.client.force_authenticate(user=self.owner1)
        response = self.client.put(
            f"/api/pets/{pet.id}/",
            {
                "name": "Rex",
                "species": "DOG",
                "breed": "Labrador",
                "customer": self.cust2.id,
            },
            format="json",
            HTTP_HOST="pet1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "CUSTOMER_WRONG_TENANT")

    def test_list_pets_only_current_tenant(self):
        """List returns only pets from current tenant."""
        set_current_tenant(self.tenant1)
        Pet.objects.create(name="Rex", species="DOG", breed="Labrador", customer=self.cust1)
        set_current_tenant(self.tenant2)
        Pet.objects.create(name="Mimi", species="CAT", breed="Siamês", customer=self.cust2)

        self.client.force_authenticate(user=self.owner1)
        response = self.client.get("/api/pets/", HTTP_HOST="pet1.localhost:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Rex")

    def test_delete_customer_removes_pets_api(self):
        """Delete customer via API -> associated pets are deleted."""
        set_current_tenant(self.tenant1)
        pet = Pet.objects.create(
            name="Rex", species="DOG", breed="Labrador", customer=self.cust1
        )
        self.assertEqual(Pet.all_objects.count(), 1)

        self.client.force_authenticate(user=self.owner1)
        del_resp = self.client.delete(
            f"/api/customers/{self.cust1.id}/",
            HTTP_HOST="pet1.localhost:8000",
        )
        self.assertEqual(del_resp.status_code, 204)
        self.assertEqual(Pet.all_objects.count(), 0)


class ServiceAPITests(TestCase):
    """Integration tests for Service CRUD. DoD: price=-10, duration=0 return 400 with standardized error."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(subdomain="svc1", name="Tenant 1")
        self.owner = User.objects.create_user(
            email="owner@svc.com", password="pass123", role="OWNER", tenant=self.tenant
        )

    def test_price_negative_returns_400_standard_format(self):
        """price=-10 returns 400 with standardized error format."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/services/",
            {
                "name": "Teste",
                "description": "Desc",
                "price": "-10",
                "duration_minutes": 60,
            },
            format="json",
            HTTP_HOST="svc1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "INVALID_PRICE")
        self.assertIn("preço", response.data["error"]["message"].lower())

    def test_duration_zero_returns_400_standard_format(self):
        """duration=0 returns 400 with standardized error format."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/services/",
            {
                "name": "Teste",
                "description": "Desc",
                "price": "50.00",
                "duration_minutes": 0,
            },
            format="json",
            HTTP_HOST="svc1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "INVALID_DURATION")
        self.assertIn("duração", response.data["error"]["message"].lower())

    def test_create_service_success(self):
        """Create service with valid data."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/services/",
            {
                "name": "Banho Premium",
                "description": "Banho completo",
                "price": "75.00",
                "duration_minutes": 90,
            },
            format="json",
            HTTP_HOST="svc1.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "Banho Premium")
        self.assertEqual(response.data["price"], "75.00")
        self.assertEqual(response.data["duration_minutes"], 90)

    def test_filter_is_active_true(self):
        """Filter ?is_active=true returns only active services."""
        set_current_tenant(self.tenant)
        Service.objects.create(
            name="Ativo", price=50, duration_minutes=60, is_active=True
        )
        Service.objects.create(
            name="Inativo", price=30, duration_minutes=30, is_active=False
        )
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(
            "/api/services/?is_active=true", HTTP_HOST="svc1.localhost:8000"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Ativo")


class AppointmentEndTimeTests(TestCase):
    """DoD: Creating appointment saves end_time automatically without passing in payload."""

    def setUp(self):
        self.tenant = Tenant.objects.create(subdomain="apt1", name="Tenant 1")
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="João",
            cpf="39053344705",
            email="joao@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Rex", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant,
            name="Banho",
            price=50,
            duration_minutes=60,
        )

    def test_create_appointment_saves_end_time_automatically(self):
        """end_time is computed from scheduled_at + service.duration_minutes, no payload needed."""
        from datetime import timedelta

        from django.utils import timezone

        set_current_tenant(self.tenant)
        scheduled_at = timezone.make_aware(timezone.datetime(2026, 2, 10, 14, 0, 0))
        appt = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=scheduled_at,
            status="PRE_BOOKED",
        )
        self.assertIsNotNone(appt.end_time)
        expected_end = scheduled_at + timedelta(minutes=self.service.duration_minutes)
        self.assertEqual(appt.end_time, expected_end)
        self.assertIsNotNone(appt.expires_at)
        self.assertGreaterEqual(
            (appt.expires_at - timezone.now()).total_seconds(), 9 * 60,
            "expires_at should be ~10 min from now"
        )

    def test_pre_book_endpoint_returns_end_time_without_payload(self):
        """POST /appointments/pre-book/ returns end_time without client sending it."""
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner@apt.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": self.pet.id,
                "service_id": self.service.id,
                "scheduled_at": "2026-02-10T14:00:00",
            },
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("appointment_id", response.data)
        self.assertIn("end_time", response.data)
        self.assertIn("expires_at", response.data)
        self.assertIsNotNone(response.data["expires_at"])
        self.assertEqual(response.data["status"], "PRE_BOOKED")

    def test_pre_book_same_slot_returns_409_conflict(self):
        """Booking same pet+service+time twice returns 409 APPOINTMENT_CONFLICT."""
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner2@apt.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.owner)
        payload = {
            "pet_id": self.pet.id,
            "service_id": self.service.id,
            "scheduled_at": "2026-02-10T14:00:00",
        }
        r1 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r1.status_code, 201)
        r2 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.data["error"]["code"], "APPOINTMENT_CONFLICT")
        self.assertIn("ocupado", r2.data["error"]["message"].lower())

    def test_cancelled_appointment_does_not_block_same_slot(self):
        """CANCELLED appointments do not block booking the same slot (DoD)."""
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner3@apt.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.owner)
        payload = {
            "pet_id": self.pet.id,
            "service_id": self.service.id,
            "scheduled_at": "2026-02-15T10:00:00",
        }
        r1 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r1.status_code, 201)
        apt_id = r1.data["appointment_id"]
        set_current_tenant(self.tenant)
        Appointment.all_objects.filter(id=apt_id).update(status="CANCELLED")
        r2 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r2.status_code, 201, "CANCELLED slot should allow new booking")

    def test_expired_appointment_does_not_block_same_slot(self):
        """EXPIRED appointments do not block booking the same slot (DoD)."""
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="owner4@apt.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.client.force_authenticate(user=self.owner)
        payload = {
            "pet_id": self.pet.id,
            "service_id": self.service.id,
            "scheduled_at": "2026-02-16T14:00:00",
        }
        r1 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r1.status_code, 201)
        apt_id = r1.data["appointment_id"]
        set_current_tenant(self.tenant)
        Appointment.all_objects.filter(id=apt_id).update(status="EXPIRED")
        r2 = self.client.post(
            "/api/appointments/pre-book/",
            payload,
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        self.assertEqual(r2.status_code, 201, "EXPIRED slot should allow new booking")


class ExceptionHandlerTests(TestCase):
    """Tests for custom exception handler."""

    def test_integrity_error_no_overlap_returns_409_schedule_conflict(self):
        """IntegrityError from no_overlap constraint returns 409 SCHEDULE_CONFLICT."""
        from django.db import IntegrityError
        from rest_framework.request import Request
        from rest_framework.views import APIView

        from .exception_handler import custom_exception_handler

        exc = IntegrityError(
            'could not create exclusion constraint "no_overlap"\n'
            "DETAIL: Key (tenant_id, tstzrange(...)) conflicts"
        )
        request = APIRequestFactory().get("/")
        context = {"view": APIView(), "request": Request(request)}
        response = custom_exception_handler(exc, context)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["code"], "SCHEDULE_CONFLICT")
        self.assertIn("Conflito", response.data["error"]["message"])


class ExpirePrebookingsCommandTests(TestCase):
    """DoD: python manage.py expire_prebookings expira corretamente + log mostra contagem."""

    def setUp(self):
        from django.utils import timezone

        self.tenant = Tenant.objects.create(subdomain="exp1", name="Tenant 1")
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="João",
            cpf="39053344705",
            email="joao@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Rex", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=50, duration_minutes=60
        )
        self.now = timezone.now()
        self.past = self.now - timedelta(minutes=15)

    def test_expire_prebookings_marks_expired_and_shows_count(self):
        """Command expires PRE_BOOKED appointments with expires_at < now and logs count."""
        set_current_tenant(self.tenant)
        apt1 = Appointment.all_objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.now + timedelta(hours=1),
            status="PRE_BOOKED",
            expires_at=self.past,
        )
        apt2 = Appointment.all_objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.now + timedelta(hours=2),
            status="PRE_BOOKED",
            expires_at=self.past,
        )
        self.assertEqual(Appointment.all_objects.filter(status="PRE_BOOKED").count(), 2)

        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("expire_prebookings", stdout=out)
        output = out.getvalue()

        self.assertIn("2", output)
        self.assertIn("Expired", output)
        self.assertEqual(Appointment.all_objects.filter(status="PRE_BOOKED").count(), 0)
        self.assertEqual(Appointment.all_objects.filter(status="EXPIRED").count(), 2)
        apt1.refresh_from_db()
        apt2.refresh_from_db()
        self.assertEqual(apt1.status, "EXPIRED")
        self.assertEqual(apt2.status, "EXPIRED")

    def test_expire_prebookings_ignores_future_expires_at(self):
        """Appointments with expires_at in future are not expired."""
        set_current_tenant(self.tenant)
        future_expires = self.now + timedelta(minutes=5)
        Appointment.all_objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.now + timedelta(hours=1),
            status="PRE_BOOKED",
            expires_at=future_expires,
        )
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("expire_prebookings", stdout=out)
        output = out.getvalue()

        self.assertIn("0", output)
        self.assertEqual(Appointment.all_objects.filter(status="PRE_BOOKED").count(), 1)


class PaymentModelTests(TestCase):
    """DoD: Payment.objects.create funciona."""

    def setUp(self):
        from django.utils import timezone

        self.tenant = Tenant.objects.create(subdomain="pay1", name="Tenant 1")
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="João",
            cpf="39053344705",
            email="joao@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Rex", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=50, duration_minutes=60
        )
        set_current_tenant(self.tenant)
        self.appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=timezone.now() + timedelta(hours=1),
            status="PRE_BOOKED",
        )

    def test_payment_create(self):
        """Payment.objects.create works with required fields."""
        payment = Payment.objects.create(
            appointment=self.appointment,
            amount=25.50,
        )
        self.assertEqual(payment.status, "PENDING")
        self.assertEqual(payment.amount, 25.50)
        self.assertFalse(payment.webhook_processed)
        self.assertIsNone(payment.payment_id_external)
        self.assertEqual(Payment.all_objects.count(), 1)


class CheckoutAPITests(TestCase):
    """DoD: checkout returns payment_link, creates Payment with 50% amount, validates PRE_BOOKED."""

    def setUp(self):
        from django.utils import timezone

        self.client = APIClient()
        self.tenant = Tenant.objects.create(subdomain="chk1", name="Tenant 1")
        self.owner = User.objects.create_user(
            email="owner@chk.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="João",
            cpf="39053344705",
            email="joao@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Rex", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=100, duration_minutes=60
        )
        set_current_tenant(self.tenant)
        self.appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status="PRE_BOOKED",
        )

    @patch("mercadopago.SDK")
    def test_checkout_creates_payment_and_returns_link(self, mock_sdk):
        """Checkout creates Payment with 50% amount and returns payment_link from MP."""
        mock_preference = MagicMock()
        mock_preference.create.return_value = {
            "response": {
                "id": "mp-pref-123",
                "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=mp-pref-123",
            }
        }
        mock_sdk.return_value.preference.return_value = mock_preference

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/payments/checkout/",
            {"appointment_id": self.appointment.id},
            format="json",
            HTTP_HOST="chk1.localhost:8000",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("payment_link", response.data)
        self.assertIn("mp-pref-123", response.data["payment_link"])

        payment = Payment.all_objects.get(appointment=self.appointment)
        self.assertEqual(payment.amount, Decimal("50.00"))
        self.assertEqual(payment.status, "PENDING")
        self.assertEqual(payment.payment_id_external, "mp-pref-123")

    def test_checkout_appointment_not_prebooked_returns_400(self):
        """Checkout with appointment not PRE_BOOKED returns 400."""
        self.appointment.status = "CONFIRMED"
        self.appointment.save()

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/payments/checkout/",
            {"appointment_id": self.appointment.id},
            format="json",
            HTTP_HOST="chk1.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("PRE_BOOKED", response.data["error"]["message"])

    @patch("mercadopago.SDK")
    def test_checkout_wrong_tenant_returns_400(self, mock_sdk):
        """Checkout with appointment from another tenant returns 400."""
        tenant2 = Tenant.objects.create(subdomain="chk2", name="Tenant 2")
        owner2 = User.objects.create_user(
            email="owner2@chk.com", password="pass123", role="OWNER", tenant=tenant2
        )
        self.client.force_authenticate(user=owner2)
        response = self.client.post(
            "/api/payments/checkout/",
            {"appointment_id": self.appointment.id},
            format="json",
            HTTP_HOST="chk2.localhost:8000",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("outro tenant", response.data["error"]["message"].lower())


class MercadoPagoWebhookTests(TestCase):
    """DoD: webhook processes payment notification, updates Payment and Appointment status."""

    def setUp(self):
        from django.utils import timezone

        self.client = APIClient()
        self.tenant = Tenant.objects.create(subdomain="webhook1", name="Tenant Webhook")
        self.owner = User.objects.create_user(
            email="owner@webhook.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="Cliente Webhook",
            cpf="12345678901",
            email="cliente@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Dog", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=100, duration_minutes=60
        )
        set_current_tenant(self.tenant)
        self.appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status="PRE_BOOKED",
        )
        self.payment = Payment.objects.create(
            appointment=self.appointment,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="mp-12345",
        )

    @patch("mercadopago.SDK")
    def test_webhook_approved_payment_confirms_appointment(self, mock_sdk):
        """Webhook with approved payment updates Payment to APPROVED and Appointment to CONFIRMED."""
        mock_payment = MagicMock()
        mock_payment.get.return_value = {
            "response": {
                "id": "mp-12345",
                "status": "approved",
            }
        }
        mock_sdk.return_value.payment.return_value = mock_payment

        webhook_payload = {
            "type": "payment",
            "data": {"id": "mp-12345"},
        }

        response = self.client.post(
            "/api/webhooks/mercadopago/",
            webhook_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "processed")
        self.assertEqual(response.data["payment_status"], "approved")

        # Refresh from database
        self.payment.refresh_from_db()
        self.appointment.refresh_from_db()

        self.assertEqual(self.payment.status, "APPROVED")
        self.assertTrue(self.payment.webhook_processed)
        self.assertEqual(self.appointment.status, "CONFIRMED")

    @patch("mercadopago.SDK")
    def test_webhook_rejected_payment_updates_status(self, mock_sdk):
        """Webhook with rejected payment updates Payment to REJECTED."""
        mock_payment = MagicMock()
        mock_payment.get.return_value = {
            "response": {
                "id": "mp-12345",
                "status": "rejected",
            }
        }
        mock_sdk.return_value.payment.return_value = mock_payment

        webhook_payload = {
            "type": "payment",
            "data": {"id": "mp-12345"},
        }

        response = self.client.post(
            "/api/webhooks/mercadopago/",
            webhook_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["payment_status"], "rejected")

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "REJECTED")
        self.assertTrue(self.payment.webhook_processed)

    @patch("mercadopago.SDK")
    def test_webhook_already_processed_returns_200(self, mock_sdk):
        """Webhook for already processed payment returns 200 without reprocessing."""
        self.payment.webhook_processed = True
        self.payment.save()

        webhook_payload = {
            "type": "payment",
            "data": {"id": "mp-12345"},
        }

        response = self.client.post(
            "/api/webhooks/mercadopago/",
            webhook_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "already_processed")

        # Verify SDK was not called
        mock_sdk.assert_not_called()

    def test_webhook_payment_not_found_returns_404(self):
        """Webhook with unknown payment_id returns 404."""
        webhook_payload = {
            "type": "payment",
            "data": {"id": "unknown-payment-id"},
        }

        response = self.client.post(
            "/api/webhooks/mercadopago/",
            webhook_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "PAYMENT_NOT_FOUND")

    def test_webhook_ignores_non_payment_notifications(self):
        """Webhook ignores non-payment notification types."""
        webhook_payload = {
            "type": "plan",
            "data": {"id": "some-id"},
        }

        response = self.client.post(
            "/api/webhooks/mercadopago/",
            webhook_payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ignored")


class WebhookIdempotencyTests(TestCase):
    """DoD: Reenviar mesmo webhook 5x = apenas 1 processamento."""

    def setUp(self):
        from django.utils import timezone

        self.client = APIClient()
        self.tenant = Tenant.objects.create(subdomain="idempotent", name="Tenant Idempotent")
        self.owner = User.objects.create_user(
            email="owner@idempotent.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="Cliente",
            cpf="12345678901",
            email="cliente@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Dog", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=100, duration_minutes=60
        )
        set_current_tenant(self.tenant)
        self.appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status="PRE_BOOKED",
        )
        self.payment = Payment.objects.create(
            appointment=self.appointment,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="mp-idempotent-123",
        )

    @patch("mercadopago.SDK")
    def test_webhook_idempotency_five_calls_one_processing(self, mock_sdk):
        """Sending the same webhook 5 times should only process once."""
        mock_payment = MagicMock()
        mock_payment.get.return_value = {
            "response": {
                "id": "mp-idempotent-123",
                "status": "approved",
            }
        }
        mock_sdk.return_value.payment.return_value = mock_payment

        webhook_payload = {
            "type": "payment",
            "data": {"id": "mp-idempotent-123"},
        }

        # Send webhook 5 times
        for i in range(5):
            response = self.client.post(
                "/api/webhooks/mercadopago/",
                webhook_payload,
                format="json",
            )
            
            self.assertEqual(response.status_code, 200, f"Call {i+1} failed")
            
            if i == 0:
                # First call should process
                self.assertEqual(response.data["status"], "processed")
                self.assertEqual(response.data["payment_status"], "approved")
            else:
                # Subsequent calls should be ignored (idempotency)
                self.assertEqual(response.data["status"], "already_processed")

        # Verify payment was only updated once
        self.payment.refresh_from_db()
        self.appointment.refresh_from_db()
        
        self.assertEqual(self.payment.status, "APPROVED")
        self.assertTrue(self.payment.webhook_processed)
        self.assertEqual(self.appointment.status, "CONFIRMED")
        
        # Verify MP API was only called once (first call)
        self.assertEqual(mock_payment.get.call_count, 1)


class AppointmentTransitionTests(TestCase):
    """DoD: All valid transitions pass, invalid ones raise InvalidTransitionError."""

    def setUp(self):
        from django.utils import timezone

        self.tenant = Tenant.objects.create(subdomain="transitions", name="Transitions Test")
        self.owner = User.objects.create_user(
            email="owner@transitions.com", password="pass123", role="OWNER", tenant=self.tenant
        )
        self.customer = Customer.all_objects.create(
            tenant=self.tenant,
            name="Cliente",
            cpf="12345678901",
            email="cliente@example.com",
            phone="11999999999",
        )
        self.pet = Pet.all_objects.create(
            tenant=self.tenant, name="Dog", species="DOG", breed="Labrador", customer=self.customer
        )
        self.service = Service.all_objects.create(
            tenant=self.tenant, name="Banho", price=100, duration_minutes=60
        )
        set_current_tenant(self.tenant)
        self.base_scheduled_at = timezone.now() + timedelta(hours=2)

    def test_prebooked_to_confirmed_valid(self):
        """PRE_BOOKED → CONFIRMED is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="PRE_BOOKED",
        )
        
        result = AppointmentService.transition(appointment, "CONFIRMED")
        
        self.assertEqual(result.status, "CONFIRMED")
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")

    def test_prebooked_to_expired_valid(self):
        """PRE_BOOKED → EXPIRED is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="PRE_BOOKED",
        )
        
        result = AppointmentService.transition(appointment, "EXPIRED")
        
        self.assertEqual(result.status, "EXPIRED")

    def test_prebooked_to_cancelled_valid(self):
        """PRE_BOOKED → CANCELLED is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="PRE_BOOKED",
        )
        
        result = AppointmentService.transition(appointment, "CANCELLED")
        
        self.assertEqual(result.status, "CANCELLED")

    def test_confirmed_to_completed_valid(self):
        """CONFIRMED → COMPLETED is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="CONFIRMED",
        )
        
        result = AppointmentService.transition(appointment, "COMPLETED")
        
        self.assertEqual(result.status, "COMPLETED")

    def test_confirmed_to_no_show_valid(self):
        """CONFIRMED → NO_SHOW is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="CONFIRMED",
        )
        
        result = AppointmentService.transition(appointment, "NO_SHOW")
        
        self.assertEqual(result.status, "NO_SHOW")

    def test_confirmed_to_cancelled_valid(self):
        """CONFIRMED → CANCELLED is a valid transition."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="CONFIRMED",
        )
        
        result = AppointmentService.transition(appointment, "CANCELLED")
        
        self.assertEqual(result.status, "CANCELLED")

    def test_prebooked_to_completed_invalid(self):
        """PRE_BOOKED → COMPLETED is INVALID."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="PRE_BOOKED",
        )
        
        with self.assertRaises(InvalidTransitionError) as context:
            AppointmentService.transition(appointment, "COMPLETED")
        
        self.assertIn("PRE_BOOKED", str(context.exception))
        self.assertIn("COMPLETED", str(context.exception))
        
        # Status should not have changed
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "PRE_BOOKED")

    def test_confirmed_to_expired_invalid(self):
        """CONFIRMED → EXPIRED is INVALID."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="CONFIRMED",
        )
        
        with self.assertRaises(InvalidTransitionError):
            AppointmentService.transition(appointment, "EXPIRED")
        
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")

    def test_completed_to_anything_invalid(self):
        """COMPLETED is a terminal state - no transitions allowed."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="COMPLETED",
        )
        
        # Try all possible transitions from COMPLETED
        for target_status in ["PRE_BOOKED", "CONFIRMED", "CANCELLED", "EXPIRED", "NO_SHOW"]:
            with self.assertRaises(InvalidTransitionError):
                AppointmentService.transition(appointment, target_status)

    def test_cancelled_to_anything_invalid(self):
        """CANCELLED is a terminal state - no transitions allowed."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="CANCELLED",
        )
        
        with self.assertRaises(InvalidTransitionError):
            AppointmentService.transition(appointment, "CONFIRMED")

    def test_expired_to_anything_invalid(self):
        """EXPIRED is a terminal state - no transitions allowed."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="EXPIRED",
        )
        
        with self.assertRaises(InvalidTransitionError):
            AppointmentService.transition(appointment, "CONFIRMED")

    def test_no_show_to_anything_invalid(self):
        """NO_SHOW is a terminal state - no transitions allowed."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="NO_SHOW",
        )
        
        with self.assertRaises(InvalidTransitionError):
            AppointmentService.transition(appointment, "COMPLETED")

    def test_get_allowed_transitions(self):
        """get_allowed_transitions returns correct transitions."""
        self.assertEqual(
            set(AppointmentService.get_allowed_transitions("PRE_BOOKED")),
            {"CONFIRMED", "EXPIRED", "CANCELLED"},
        )
        self.assertEqual(
            set(AppointmentService.get_allowed_transitions("CONFIRMED")),
            {"COMPLETED", "NO_SHOW", "CANCELLED"},
        )
        self.assertEqual(AppointmentService.get_allowed_transitions("COMPLETED"), [])
        self.assertEqual(AppointmentService.get_allowed_transitions("CANCELLED"), [])

    def test_can_transition(self):
        """can_transition returns True for valid, False for invalid."""
        self.assertTrue(AppointmentService.can_transition("PRE_BOOKED", "CONFIRMED"))
        self.assertTrue(AppointmentService.can_transition("CONFIRMED", "COMPLETED"))
        self.assertFalse(AppointmentService.can_transition("PRE_BOOKED", "COMPLETED"))
        self.assertFalse(AppointmentService.can_transition("COMPLETED", "CONFIRMED"))

    def test_invalid_transition_error_attributes(self):
        """InvalidTransitionError has correct attributes."""
        appointment = Appointment.objects.create(
            pet=self.pet,
            service=self.service,
            scheduled_at=self.base_scheduled_at,
            status="PRE_BOOKED",
        )
        
        try:
            AppointmentService.transition(appointment, "COMPLETED")
        except InvalidTransitionError as e:
            self.assertEqual(e.current_status, "PRE_BOOKED")
            self.assertEqual(e.new_status, "COMPLETED")
            self.assertEqual(e.allowed_transitions, ["CONFIRMED", "EXPIRED", "CANCELLED"])

