"""
RN06: Fluxo de Pagamento (Mercado Pago)

Checkout cria Payment (50% do preço) e retorna payment_link.
Webhook approved: Payment→APPROVED, Appointment→CONFIRMED.
Webhook rejected: Payment→REJECTED, Appointment permanece PRE_BOOKED.
Idempotência: webhook processado apenas uma vez.
"""
import pytest
import responses
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import Payment, Appointment
from tests.factories import TenantFactory, UserFactory, AppointmentFactory


@pytest.mark.django_db
class TestPaymentFlow:
    """RN06: Mercado Pago payment flow."""

    @responses.activate
    def test_checkout_creates_payment_and_returns_link(self):
        """POST /payments/checkout/ cria Payment e retorna payment_link."""
        tenant = TenantFactory(subdomain="pay1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(
            tenant=tenant,
            status="PRE_BOOKED",
        )
        apt.service.price = Decimal("100.00")
        apt.service.save()
        
        # Mock Mercado Pago preference creation
        # SDK usa endpoint POST /checkout/preferences
        responses.add(
            responses.POST,
            "https://api.mercadopago.com/checkout/preferences",
            json={
                "id": "MP123456",
                "init_point": "https://mercadopago.com.br/checkout/v1/redirect?pref_id=MP123456",
            },
            status=201,
        )
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/payments/checkout/",
            {"appointment_id": apt.id},
            format="json",
            HTTP_HOST="pay1.localhost:8000",
        )
        
        assert response.status_code == 201
        assert "payment_link" in response.data
        
        # Verificar Payment criado
        payment = Payment.all_objects.get(appointment=apt)
        assert payment.amount == Decimal("50.00")  # 50% de 100
        assert payment.status == "PENDING"
        assert payment.payment_id_external == "MP123456"

    @responses.activate
    def test_webhook_approved_confirms_appointment(self):
        """Webhook com status=approved confirma appointment."""
        tenant = TenantFactory(subdomain="webhook1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MP999",
        )
        
        # Mock Mercado Pago get payment
        # SDK usa endpoint GET /v1/payments/{id}
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MP999",
            json={"status": "approved"},
            status=200,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MP999"}},
            format="json",
        )
        
        assert response.status_code == 200
        
        payment.refresh_from_db()
        apt.refresh_from_db()
        
        assert payment.status == "APPROVED"
        assert payment.webhook_processed is True
        assert apt.status == "CONFIRMED"

    @responses.activate
    def test_webhook_rejected_keeps_prebooked(self):
        """Webhook com status=rejected mantém appointment PRE_BOOKED."""
        tenant = TenantFactory(subdomain="webhook2")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MP888",
        )
        
        # Mock Mercado Pago get payment
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MP888",
            json={"status": "rejected"},
            status=200,
        )
        
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MP888"}},
            format="json",
        )
        
        assert response.status_code == 200
        
        payment.refresh_from_db()
        apt.refresh_from_db()
        
        assert payment.status == "REJECTED"
        assert payment.webhook_processed is True
        assert apt.status == "PRE_BOOKED"  # Não mudou

    @responses.activate
    def test_webhook_idempotency_processes_once(self):
        """Webhook duplicado é processado apenas uma vez."""
        tenant = TenantFactory(subdomain="webhook3")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        payment = Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="PENDING",
            payment_id_external="MP777",
        )
        
        # Mock Mercado Pago get payment
        responses.add(
            responses.GET,
            "https://api.mercadopago.com/v1/payments/MP777",
            json={"status": "approved"},
            status=200,
        )
        
        client = APIClient()
        
        # Primeiro webhook
        r1 = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MP777"}},
            format="json",
        )
        assert r1.status_code == 200
        
        # Segundo webhook (duplicado)
        r2 = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "MP777"}},
            format="json",
        )
        assert r2.status_code == 200
        assert "already_processed" in r2.data["status"]
        
        # Verificar que status não foi alterado múltiplas vezes
        payment.refresh_from_db()
        assert payment.webhook_processed is True
        assert payment.status == "APPROVED"

    def test_payment_not_found_returns_404(self):
        """Webhook com payment_id inexistente retorna 404."""
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "payment", "data": {"id": "NONEXISTENT"}},
            format="json",
        )
        
        assert response.status_code == 404
        assert response.data["error"]["code"] == "PAYMENT_NOT_FOUND"

    def test_non_payment_notification_is_ignored(self):
        """Webhook type != payment é ignorado."""
        client = APIClient()
        response = client.post(
            "/api/webhooks/mercadopago/",
            {"type": "subscription", "data": {"id": "SUB123"}},
            format="json",
        )
        
        assert response.status_code == 200
        assert response.data["status"] == "ignored"
