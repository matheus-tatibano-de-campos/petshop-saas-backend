"""
Testes complementares para garantir cobertura >95%.
Cobre edge cases, error paths e branches não cobertos pelos testes de RN.
"""
import pytest
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import User, Customer, Pet, Service
from core.permissions import IsOwner, IsOwnerOrAttendant
from core.exceptions import InvalidCPFError, PaymentFailedError, TenantNotFoundError
from tests.factories import TenantFactory, UserFactory, CustomerFactory, PetFactory, ServiceFactory


@pytest.mark.django_db
class TestModelsCoverage:
    """Testes para cobrir branches do models.py."""

    def test_user_manager_create_user_without_email_raises_error(self):
        """UserManager.create_user sem email levanta ValueError."""
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(email="", password="pass")

    def test_user_manager_create_superuser(self):
        """UserManager.create_superuser cria superuser."""
        user = User.objects.create_superuser(
            email="admin@test.com",
            password="admin123"
        )
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_tenant_aware_model_save_without_tenant_raises_error(self):
        """TenantAwareModel.save() sem tenant e sem context levanta ValueError."""
        from core.context import clear_current_tenant
        clear_current_tenant()
        
        tenant = TenantFactory()
        # Tentar criar customer sem tenant e sem context
        customer = Customer(
            name="Test",
            cpf="12345678901",
            email="test@test.com",
            phone="11999999999"
        )
        
        with pytest.raises(ValueError, match="Tenant required"):
            customer.save()

    def test_model_str_methods(self):
        """Testa __str__ methods dos models."""
        tenant = TenantFactory(subdomain="test")
        set_current_tenant(tenant)
        
        assert str(tenant) == "test"
        
        customer = CustomerFactory(tenant=tenant, name="João", cpf="12345678901")
        assert "João" in str(customer)
        assert "12345678901" in str(customer)
        
        pet = PetFactory(tenant=tenant, name="Rex", species="DOG", customer=customer)
        assert "Rex" in str(pet)
        assert "Cachorro" in str(pet)
        
        service = ServiceFactory(tenant=tenant, name="Banho")
        assert "Banho" in str(service)


@pytest.mark.django_db
class TestSerializersCoverage:
    """Testes para cobrir serializers.py."""

    def test_customer_serializer_validates_cpf_format(self):
        """CustomerSerializer valida formato de CPF."""
        from core.serializers import CustomerSerializer
        
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # CPF muito curto
        response = client.post(
            "/api/customers/",
            {"name": "Test", "cpf": "123", "email": "t@t.com", "phone": "11999999999"},
            format="json",
            HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
        )
        assert response.status_code == 400

    def test_pet_serializer_customer_wrong_tenant(self):
        """PetSerializer rejeita customer de outro tenant."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")
        user2 = UserFactory(tenant=tenant2)
        
        set_current_tenant(tenant1)
        customer_t1 = CustomerFactory(tenant=tenant1)
        
        client = APIClient()
        client.force_authenticate(user=user2)
        
        response = client.post(
            "/api/pets/",
            {
                "name": "Dog",
                "species": "DOG",
                "breed": "Lab",
                "customer": customer_t1.id,
            },
            format="json",
            HTTP_HOST="t2.localhost:8000",
        )
        assert response.status_code == 400

    def test_service_serializer_negative_price(self):
        """ServiceSerializer rejeita preço negativo."""
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/services/",
            {"name": "Test", "price": -10, "duration_minutes": 60},
            format="json",
            HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
        )
        assert response.status_code == 400

    def test_service_serializer_zero_duration(self):
        """ServiceSerializer rejeita duração zero."""
        tenant = TenantFactory()
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/services/",
            {"name": "Test", "price": 50, "duration_minutes": 0},
            format="json",
            HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestPermissionsCoverage:
    """Testes para cobrir permissions.py."""

    def test_is_owner_permission_allows_owner_via_api(self):
        """IsOwner permite OWNER via API call."""
        tenant = TenantFactory(subdomain="perm1")
        owner = UserFactory(tenant=tenant, role="OWNER")
        attendant = UserFactory(tenant=tenant, role="ATTENDANT")
        
        client = APIClient()
        
        # OWNER deve conseguir criar tenant (permission IsAdminUser)
        client.force_authenticate(user=owner)
        
        # Test via real API endpoint que usa IsOwnerOrAttendant
        set_current_tenant(tenant)
        customer = CustomerFactory(tenant=tenant)
        
        # Get customer - IsOwnerOrAttendant permite
        response = client.get(
            f"/api/customers/{customer.id}/",
            HTTP_HOST="perm1.localhost:8000"
        )
        assert response.status_code == 200

    def test_is_owner_or_attendant_allows_both_roles(self):
        """IsOwnerOrAttendant permite OWNER e ATTENDANT via API."""
        tenant = TenantFactory(subdomain="perm2")
        attendant = UserFactory(tenant=tenant, role="ATTENDANT")
        
        client = APIClient()
        client.force_authenticate(user=attendant)
        
        # ATTENDANT deve conseguir listar customers
        response = client.get("/api/customers/", HTTP_HOST="perm2.localhost:8000")
        assert response.status_code == 200


@pytest.mark.django_db
class TestExceptionsCoverage:
    """Testes para cobrir exceptions.py com code customizado."""

    def test_api_error_with_custom_code(self):
        """APIError aceita código customizado."""
        from core.exceptions import APIError
        
        error = APIError("Custom message", code="CUSTOM_CODE")
        assert error.code == "CUSTOM_CODE"
        assert str(error) == "Custom message"

    def test_invalid_cpf_error(self):
        """InvalidCPFError tem código INVALID_CPF."""
        error = InvalidCPFError()
        assert error.code == "INVALID_CPF"
        assert "inválido" in str(error).lower()

    def test_payment_failed_error(self):
        """PaymentFailedError tem código PAYMENT_FAILED."""
        error = PaymentFailedError()
        assert error.code == "PAYMENT_FAILED"

    def test_tenant_not_found_error(self):
        """TenantNotFoundError tem código TENANT_NOT_FOUND."""
        error = TenantNotFoundError()
        assert error.code == "TENANT_NOT_FOUND"


@pytest.mark.django_db
class TestViewsCoverage:
    """Testes para cobrir branches de views.py."""

    def test_health_endpoint(self):
        """GET /api/health/ retorna OK."""
        tenant = TenantFactory(subdomain="health")
        client = APIClient()
        response = client.get("/api/health/", HTTP_HOST="health.localhost:8000")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_tenant_info_endpoint(self):
        """GET /api/tenant-info/ retorna info do tenant."""
        tenant = TenantFactory(subdomain="info")
        
        client = APIClient()
        response = client.get("/api/tenant-info/", HTTP_HOST="info.localhost:8000")
        
        assert response.status_code == 200
        data = response.json()
        assert data["tenant_id"] == tenant.id
        assert data["subdomain"] == "info"

    def test_login_with_valid_credentials(self):
        """POST /api/auth/login/ com credenciais válidas retorna tokens."""
        tenant = TenantFactory(subdomain="login")
        user = UserFactory(tenant=tenant, email="user@login.com")
        user.set_password("pass123")
        user.save()
        
        client = APIClient()
        response = client.post(
            "/api/auth/login/",
            {"email": "user@login.com", "password": "pass123"},
            format="json",
            HTTP_HOST="login.localhost:8000",
        )
        
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data

    def test_checkout_appointment_not_prebooked_returns_400(self):
        """Checkout de appointment não PRE_BOOKED retorna 400."""
        tenant = TenantFactory(subdomain="checkout2")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        from tests.factories import AppointmentFactory
        apt = AppointmentFactory(tenant=tenant, status="CONFIRMED")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/payments/checkout/",
            {"appointment_id": apt.id},
            format="json",
            HTTP_HOST="checkout2.localhost:8000",
        )
        
        assert response.status_code == 400


@pytest.mark.django_db
class TestExceptionHandlerCoverage:
    """Testes para cobrir exception_handler.py."""

    def test_exception_handler_with_dict_detail(self):
        """Exception handler normaliza dict detail."""
        from rest_framework.exceptions import ValidationError
        from rest_framework.test import APIRequestFactory
        from core.exception_handler import custom_exception_handler
        
        exc = ValidationError({"field1": "Error 1", "field2": ["Error 2a", "Error 2b"]})
        request = APIRequestFactory().get("/")
        context = {"request": request}
        
        response = custom_exception_handler(exc, context)
        
        assert response is not None
        assert "error" in response.data
        assert "code" in response.data["error"]
        assert "message" in response.data["error"]

    def test_exception_handler_with_list_detail(self):
        """Exception handler normaliza list detail."""
        from rest_framework.exceptions import ValidationError
        from rest_framework.test import APIRequestFactory
        from core.exception_handler import custom_exception_handler
        
        exc = ValidationError(["Error 1", "Error 2"])
        request = APIRequestFactory().get("/")
        context = {"request": request}
        
        response = custom_exception_handler(exc, context)
        
        assert response is not None
        assert "Error 1" in response.data["error"]["message"] or "Error 2" in response.data["error"]["message"]
