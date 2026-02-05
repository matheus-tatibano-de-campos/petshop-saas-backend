"""
Testes de edge cases adicionais para aumentar cobertura para >95%.
Cobre paths de erro, validações e branches não exercitados.
"""
import pytest
import responses
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import Appointment, Payment
from tests.factories import (
    TenantFactory,
    UserFactory,
    CustomerFactory,
    PetFactory,
    ServiceFactory,
    AppointmentFactory,
    PaymentFactory,
)


@pytest.mark.django_db
class TestSerializersEdgeCases:
    """Edge cases para serializers não cobertos."""

    def test_pet_update_wrong_tenant_customer(self):
        """Atualizar pet com customer de outro tenant retorna 400."""
        tenant1 = TenantFactory(subdomain="pet1")
        tenant2 = TenantFactory(subdomain="pet2")
        user1 = UserFactory(tenant=tenant1)
        
        set_current_tenant(tenant1)
        customer1 = CustomerFactory(tenant=tenant1)
        pet1 = PetFactory(tenant=tenant1, customer=customer1)
        
        set_current_tenant(tenant2)
        customer2 = CustomerFactory(tenant=tenant2)
        
        client = APIClient()
        client.force_authenticate(user=user1)
        
        # Tentar atualizar pet1 com customer2 (outro tenant)
        response = client.patch(
            f"/api/pets/{pet1.id}/",
            {"customer": customer2.id},
            format="json",
            HTTP_HOST="pet1.localhost:8000",
        )
        assert response.status_code == 400

    def test_prebook_pet_not_found(self):
        """Pre-book com pet inexistente retorna 400."""
        tenant = TenantFactory(subdomain="pb1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        service = ServiceFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": 99999,
                "service_id": service.id,
                "scheduled_at": (timezone.now() + timedelta(hours=24)).isoformat(),
            },
            format="json",
            HTTP_HOST="pb1.localhost:8000",
        )
        assert response.status_code == 400

    def test_prebook_service_not_found(self):
        """Pre-book com service inexistente retorna 400."""
        tenant = TenantFactory(subdomain="pb2")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": 99999,
                "scheduled_at": (timezone.now() + timedelta(hours=24)).isoformat(),
            },
            format="json",
            HTTP_HOST="pb2.localhost:8000",
        )
        assert response.status_code == 400

    def test_prebook_pet_wrong_tenant(self):
        """Pre-book com pet de outro tenant retorna 400."""
        tenant1 = TenantFactory(subdomain="pb3")
        tenant2 = TenantFactory(subdomain="pb4")
        user1 = UserFactory(tenant=tenant1)
        
        set_current_tenant(tenant2)
        pet2 = PetFactory(tenant=tenant2)
        
        set_current_tenant(tenant1)
        service1 = ServiceFactory(tenant=tenant1)
        
        client = APIClient()
        client.force_authenticate(user=user1)
        
        response = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet2.id,
                "service_id": service1.id,
                "scheduled_at": (timezone.now() + timedelta(hours=24)).isoformat(),
            },
            format="json",
            HTTP_HOST="pb3.localhost:8000",
        )
        assert response.status_code == 400

    def test_checkout_appointment_not_found(self):
        """Checkout com appointment inexistente retorna 400."""
        tenant = TenantFactory(subdomain="co1")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/payments/checkout/",
            {"appointment_id": 99999},
            format="json",
            HTTP_HOST="co1.localhost:8000",
        )
        assert response.status_code == 400

    def test_checkout_appointment_wrong_tenant(self):
        """Checkout com appointment de outro tenant retorna 400."""
        tenant1 = TenantFactory(subdomain="co2")
        tenant2 = TenantFactory(subdomain="co3")
        user1 = UserFactory(tenant=tenant1)
        
        set_current_tenant(tenant2)
        apt2 = AppointmentFactory(tenant=tenant2, status="PRE_BOOKED")
        
        client = APIClient()
        client.force_authenticate(user=user1)
        
        response = client.post(
            "/api/payments/checkout/",
            {"appointment_id": apt2.id},
            format="json",
            HTTP_HOST="co2.localhost:8000",
        )
        assert response.status_code == 400

    @responses.activate
    def test_checkout_mercadopago_api_error_returns_500(self):
        """Checkout com erro no MP API retorna 500."""
        tenant = TenantFactory(subdomain="co4")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        
        # Mock MP API failure
        responses.add(
            responses.POST,
            "https://api.mercadopago.com/checkout/preferences",
            json={"error": "API error"},
            status=500,
        )
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/payments/checkout/",
            {"appointment_id": apt.id},
            format="json",
            HTTP_HOST="co4.localhost:8000",
        )
        assert response.status_code == 500
        assert "error" in response.data


@pytest.mark.django_db
class TestExceptionHandlerEdgeCases:
    """Edge cases para exception_handler."""

    def test_exception_handler_with_empty_message(self):
        """Exception handler trata mensagem vazia."""
        from rest_framework.exceptions import ValidationError
        from rest_framework.test import APIRequestFactory
        from core.exception_handler import custom_exception_handler, _infer_code
        
        # _infer_code com string vazia
        code = _infer_code("")
        assert code == "VALIDATION_ERROR"
        
        # _infer_code com None
        code = _infer_code(None)
        assert code == "VALIDATION_ERROR"

    def test_exception_handler_infer_code_variations(self):
        """_infer_code mapeia várias mensagens corretamente."""
        from core.exception_handler import _infer_code
        
        assert _infer_code("CPF inválido") == "INVALID_CPF"
        assert _infer_code("cpf invalido") == "INVALID_CPF"  # sem acento
        assert _infer_code("CPF já cadastrado") == "CPF_DUPLICATE"
        assert _infer_code("Customer pertence a outro tenant") == "CUSTOMER_WRONG_TENANT"
        assert _infer_code("Preço deve ser positivo") == "INVALID_PRICE"
        assert _infer_code("Duração deve ser maior") == "INVALID_DURATION"
        assert _infer_code("Horário já ocupado") == "CONFLICT_SCHEDULE"
        assert _infer_code("conflito de horário") == "CONFLICT_SCHEDULE"
        assert _infer_code("appointment deve estar PRE_BOOKED") == "INVALID_STATUS"
        assert _infer_code("Mensagem aleatória") == "VALIDATION_ERROR"

    def test_integrity_error_cpf_duplicate_returns_400(self):
        """IntegrityError sem no_overlap retorna CPF_DUPLICATE."""
        from django.db import IntegrityError
        from rest_framework.test import APIRequestFactory
        from core.exception_handler import custom_exception_handler
        
        exc = IntegrityError("DETAIL: Key (cpf, tenant_id) already exists")
        request = APIRequestFactory().get("/")
        context = {"request": request}
        
        response = custom_exception_handler(exc, context)
        assert response.status_code == 400
        assert response.data["error"]["code"] == "CPF_DUPLICATE"

    def test_unhandled_exception_returns_500(self):
        """Exceção não tratada retorna 500 INTERNAL_ERROR."""
        from rest_framework.test import APIRequestFactory
        from core.exception_handler import custom_exception_handler
        
        exc = RuntimeError("Something went wrong")
        request = APIRequestFactory().get("/")
        context = {"request": request}
        
        response = custom_exception_handler(exc, context)
        assert response.status_code == 500
        assert response.data["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.django_db
class TestViewsEdgeCases:
    """Edge cases para views.py."""

    def test_service_filter_is_active_false(self):
        """Filtrar services com is_active=false."""
        tenant = TenantFactory(subdomain="svc1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        ServiceFactory(tenant=tenant, is_active=True, name="Active")
        ServiceFactory(tenant=tenant, is_active=False, name="Inactive")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.get(
            "/api/services/?is_active=false",
            HTTP_HOST="svc1.localhost:8000",
        )
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Inactive"

    def test_appointment_update_via_put(self):
        """PUT /appointments/{id}/ atualiza appointment."""
        tenant = TenantFactory(subdomain="apt1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.put(
            f"/api/appointments/{apt.id}/",
            {
                "pet": apt.pet.id,
                "service": apt.service.id,
                "scheduled_at": apt.scheduled_at.isoformat(),
                "status": "CONFIRMED",
            },
            format="json",
            HTTP_HOST="apt1.localhost:8000",
        )
        assert response.status_code == 200

    def test_delete_customer(self):
        """DELETE /customers/{id}/ remove customer."""
        tenant = TenantFactory(subdomain="del1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        customer = CustomerFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.delete(
            f"/api/customers/{customer.id}/",
            HTTP_HOST="del1.localhost:8000",
        )
        assert response.status_code == 204

    def test_delete_appointment(self):
        """DELETE /appointments/{id}/ remove appointment."""
        tenant = TenantFactory(subdomain="del2")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.delete(
            f"/api/appointments/{apt.id}/",
            HTTP_HOST="del2.localhost:8000",
        )
        assert response.status_code == 204

    @responses.activate
    def test_webhook_mp_api_query_error(self):
        """Webhook com erro ao consultar MP API retorna 500."""
        tenant = TenantFactory(subdomain="wh1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPERR",
        )
        
        # Mock MP API error
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPERR",
            json={"error": "Internal error"},
            status=500,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MPERR"}},
            format="json",
        )
        
        assert response.status_code == 500
        assert "error" in response.data

    def test_webhook_missing_payment_id(self):
        """Webhook sem payment ID retorna 400."""
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {}},  # Missing ID
            format="json",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "MISSING_PAYMENT_ID"

    @responses.activate
    def test_webhook_pending_status_returns_pending(self):
        """Webhook com status pending retorna pending."""
        tenant = TenantFactory(subdomain="wh2")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPPEND",
        )
        
        # Mock MP API pending
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPPEND",
            json={"status": "in_process"},
            status=200,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MPPEND"}},
            format="json",
        )
        
        assert response.status_code == 200
        assert response.data["payment_status"] == "in_process"


@pytest.mark.django_db
class TestServicesEdgeCases:
    """Edge cases para services.py."""

    def test_calculate_refund_uses_approved_payment(self):
        """calculate_refund usa Payment APPROVED."""
        from core.services import CancellationService
        
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        scheduled_at = timezone.now() + timedelta(hours=30)
        apt = AppointmentFactory(
            tenant=tenant,
            status="CONFIRMED",
            scheduled_at=scheduled_at,
        )
        
        # Payment APPROVED
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        # >24h: 90% de 50 = 45
        assert refund == Decimal("45.00")


@pytest.mark.django_db
class TestAuthenticationCoverage:
    """Testes de autenticação."""

    def test_login_invalid_credentials_returns_401(self):
        """Login com credenciais inválidas retorna 401."""
        tenant = TenantFactory(subdomain="auth1")
        UserFactory(tenant=tenant, email="user@auth.com", password="correct123")
        
        client = APIClient()
        response = client.post(
            "/api/auth/login/",
            {"email": "user@auth.com", "password": "wrongpass"},
            format="json",
            HTTP_HOST="auth1.localhost:8000",
        )
        
        assert response.status_code == 401

    def test_refresh_token_returns_new_access_token(self):
        """POST /api/auth/refresh/ retorna novo access token."""
        tenant = TenantFactory(subdomain="auth2")
        user = UserFactory(tenant=tenant, email="user@auth2.com")
        user.set_password("pass123")
        user.save()
        
        client = APIClient()
        
        # Get tokens
        login_response = client.post(
            "/api/auth/login/",
            {"email": "user@auth2.com", "password": "pass123"},
            format="json",
            HTTP_HOST="auth2.localhost:8000",
        )
        refresh_token = login_response.data["refresh"]
        
        # Refresh
        response = client.post(
            "/api/auth/refresh/",
            {"refresh": refresh_token},
            format="json",
            HTTP_HOST="auth2.localhost:8000",
        )
        
        assert response.status_code == 200
        assert "access" in response.data

    def test_unauthenticated_request_returns_401(self):
        """Request sem autenticação retorna 401."""
        tenant = TenantFactory(subdomain="noauth")
        
        client = APIClient()
        # Sem force_authenticate
        
        response = client.get("/api/customers/", HTTP_HOST="noauth.localhost:8000")
        assert response.status_code == 401


@pytest.mark.django_db
class TestCRUDOperationsCoverage:
    """Testes de CRUD para cobrir views."""

    def test_list_and_detail_operations(self):
        """GET list e detail de customers, pets, services."""
        tenant = TenantFactory(subdomain="crud1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        customer = CustomerFactory(tenant=tenant)
        pet = PetFactory(tenant=tenant, customer=customer)
        service = ServiceFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # List customers
        r = client.get("/api/customers/", HTTP_HOST="crud1.localhost:8000")
        assert r.status_code == 200
        assert len(r.data) >= 1
        
        # Detail customer
        r = client.get(f"/api/customers/{customer.id}/", HTTP_HOST="crud1.localhost:8000")
        assert r.status_code == 200
        
        # List pets
        r = client.get("/api/pets/", HTTP_HOST="crud1.localhost:8000")
        assert r.status_code == 200
        
        # List services
        r = client.get("/api/services/", HTTP_HOST="crud1.localhost:8000")
        assert r.status_code == 200

    def test_update_operations(self):
        """PUT/PATCH de customers, pets, services."""
        tenant = TenantFactory(subdomain="upd1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        customer = CustomerFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # Update customer
        r = client.patch(
            f"/api/customers/{customer.id}/",
            {"name": "Updated Name"},
            format="json",
            HTTP_HOST="upd1.localhost:8000",
        )
        assert r.status_code == 200
        
        # Update service
        r = client.patch(
            f"/api/services/{service.id}/",
            {"is_active": False},
            format="json",
            HTTP_HOST="upd1.localhost:8000",
        )
        assert r.status_code == 200
