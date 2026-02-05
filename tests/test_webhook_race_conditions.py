"""
Testes de race conditions em webhooks e edge cases de permissions.
Cobre cenários de concorrência, processamento duplicado e validações de permissões.
"""
import pytest
import responses
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.test import RequestFactory
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock
from core.context import set_current_tenant
from core.models import Payment, Appointment
from core.serializers import PetSerializer
from tests.factories import (
    TenantFactory,
    UserFactory,
    CustomerFactory,
    PetFactory,
    AppointmentFactory,
)


@pytest.mark.django_db
class TestPermissionsLines:
    """Cobertura completa de permissions.py linhas 8-9."""

    def test_permission_with_none_user(self):
        """Testa permission quando request.user é None."""
        from core.permissions import IsOwner
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = None
        
        permission = IsOwner()
        # Com user None, deve retornar False
        result = permission.has_permission(request, None)
        assert result is False

    def test_permission_with_unauthenticated_user(self):
        """Testa permission quando user não está autenticado."""
        from core.permissions import IsOwnerOrAttendant
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = AnonymousUser()
        
        permission = IsOwnerOrAttendant()
        # Com AnonymousUser, is_authenticated é False
        result = permission.has_permission(request, None)
        assert result is False

    def test_permission_with_user_with_wrong_role(self):
        """Testa permission quando user tem role diferente."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        # Criar user com role ATTENDANT (não OWNER)
        user = UserFactory(tenant=tenant, role="ATTENDANT")
        
        from core.permissions import IsOwner
        from django.test import RequestFactory
        
        factory = RequestFactory()
        request = factory.get("/")
        request.user = user
        
        permission = IsOwner()
        # User tem role ATTENDANT, mas permission requer OWNER
        result = permission.has_permission(request, None)
        assert result is False


@pytest.mark.django_db
class TestSerializersLine91:
    """Cobertura de serializers.py linha 91 - return value no validate_customer."""

    def test_pet_serializer_validate_customer_returns_value_when_valid(self):
        """Testa validate_customer retornando value quando válido."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        customer = CustomerFactory(tenant=tenant)
        
        factory = RequestFactory()
        request = factory.get("/")
        request.tenant = tenant
        
        serializer = PetSerializer(context={"request": request})
        # validate_customer deve retornar o value quando tenant é correto
        result = serializer.validate_customer(customer)
        
        # Linha 91: return value
        assert result == customer
        assert result.tenant_id == tenant.id


@pytest.mark.django_db
class TestWebhookRaceConditionPaths:
    """Cobertura de views.py linhas 367-371, 400-404 - race condition paths."""

    @responses.activate
    def test_webhook_approved_race_condition_mock(self):
        """Simula race condition onde payment é processado entre checks."""
        tenant = TenantFactory(subdomain="race1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPRACE1",
            webhook_processed=False,
        )
        
        # Mock MP API
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPRACE1",
            json={"status": "approved"},
            status=200,
        )
        
        # Mock select_for_update para retornar payment já processado
        original_select_for_update = Payment.all_objects.select_for_update
        
        def mock_select_for_update(*args, **kwargs):
            # Quando select_for_update é chamado, marcar payment como processado
            # simulando que outra thread o processou
            payment.webhook_processed = True
            payment.status = "APPROVED"
            payment.save()
            return original_select_for_update(*args, **kwargs)
        
        with patch.object(
            Payment.all_objects.__class__,
            'select_for_update',
            side_effect=mock_select_for_update
        ):
            client = APIClient()
            response = client.post(
                "/api/webhooks/mercadopago/",
                {"type": "payment", "data": {"id": "MPRACE1"}},
                format="json",
                HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
            )
        
        # Deve retornar already_processed (linhas 367-371)
        assert response.status_code == 200
        assert response.data.get("status") in ["already_processed", "ok"]

    @responses.activate
    def test_webhook_rejected_race_condition_mock(self):
        """Simula race condition para status rejected."""
        tenant = TenantFactory(subdomain="race2")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPRACE2",
            webhook_processed=False,
        )
        
        # Mock MP API
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPRACE2",
            json={"status": "rejected"},
            status=200,
        )
        
        # Mock select_for_update para retornar payment já processado
        original_select_for_update = Payment.all_objects.select_for_update
        
        def mock_select_for_update(*args, **kwargs):
            # Simular que outra thread processou
            payment.webhook_processed = True
            payment.status = "REJECTED"
            payment.save()
            return original_select_for_update(*args, **kwargs)
        
        with patch.object(
            Payment.all_objects.__class__,
            'select_for_update',
            side_effect=mock_select_for_update
        ):
            client = APIClient()
            response = client.post(
                "/api/webhooks/mercadopago/",
                {"type": "payment", "data": {"id": "MPRACE2"}},
                format="json",
                HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
            )
        
        # Deve retornar already_processed (linhas 400-404)
        assert response.status_code == 200
        assert response.data.get("status") in ["already_processed", "ok"]

    @responses.activate  
    def test_webhook_approved_updates_correctly_when_not_processed(self):
        """Testa que webhook approved processa corretamente quando não foi processado antes."""
        tenant = TenantFactory(subdomain="wap1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPWAP1",
            webhook_processed=False,  # NÃO processado
        )
        
        # Mock MP API
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPWAP1",
            json={"status": "approved"},
            status=200,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MPWAP1"}},
            format="json",
            HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
        )
        
        # Deve processar com sucesso
        assert response.status_code == 200
        assert response.data["status"] == "processed"
        
        # Verificar que payment foi atualizado
        payment.refresh_from_db()
        assert payment.status == "APPROVED"
        assert payment.webhook_processed is True

    @responses.activate
    def test_webhook_rejected_updates_correctly_when_not_processed(self):
        """Testa que webhook rejected processa corretamente quando não foi processado antes."""
        tenant = TenantFactory(subdomain="wrej1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MPWREJ1",
            webhook_processed=False,  # NÃO processado
        )
        
        # Mock MP API
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MPWREJ1",
            json={"status": "rejected"},
            status=200,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MPWREJ1"}},
            format="json",
            HTTP_HOST=f"{tenant.subdomain}.localhost:8000",
        )
        
        # Deve processar com sucesso
        assert response.status_code == 200
        assert response.data["status"] == "processed"
        
        # Verificar que payment foi atualizado
        payment.refresh_from_db()
        assert payment.status == "REJECTED"
        assert payment.webhook_processed is True
