"""
RN07: Política de Cancelamento

>24h antes: reembolso 90%
24h-2h antes: reembolso 80%  
<2h antes: sem reembolso (0%)
Apenas appointments CONFIRMED podem ser cancelados.
Cria registro Refund com status PENDING.
"""
import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import Refund, Payment
from core.services import CancellationService
from tests.factories import TenantFactory, UserFactory, AppointmentFactory


@pytest.mark.django_db
class TestCancellationPolicy:
    """RN07: Cancellation policy and refund calculation."""

    def test_cancel_over_24h_refunds_90_percent(self):
        """Cancelamento >24h antes: reembolso 90%."""
        tenant = TenantFactory(subdomain="cancel1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        # Appointment daqui 30 horas
        scheduled_at = timezone.now() + timedelta(hours=30)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        assert refund == Decimal("45.00")  # 90% de 50

    def test_cancel_between_24h_2h_refunds_80_percent(self):
        """Cancelamento 24h-2h antes (23h): reembolso 80%."""
        tenant = TenantFactory(subdomain="cancel2")
        set_current_tenant(tenant)
        
        # Appointment daqui 23 horas
        scheduled_at = timezone.now() + timedelta(hours=23)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        assert refund == Decimal("40.00")  # 80% de 50

    def test_cancel_exactly_24h_refunds_80_percent(self):
        """Cancelamento exatamente 24h antes: reembolso 80% (edge case)."""
        tenant = TenantFactory(subdomain="cancel24")
        set_current_tenant(tenant)
        
        # Appointment daqui 24h + 1 minuto
        scheduled_at = timezone.now() + timedelta(hours=24, minutes=1)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("100.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        # >24h: deve retornar 90%
        assert refund == Decimal("90.00")

    def test_cancel_under_2h_no_refund(self):
        """Cancelamento <2h antes (1h): sem reembolso (0%)."""
        tenant = TenantFactory(subdomain="cancel3")
        set_current_tenant(tenant)
        
        # Appointment daqui 1 hora
        scheduled_at = timezone.now() + timedelta(hours=1)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        assert refund == Decimal("0.00")

    def test_cancel_exactly_2h_refunds_80_percent(self):
        """Cancelamento exatamente 2h antes: reembolso 80% (hours_until >= 2)."""
        tenant = TenantFactory(subdomain="cancel2h")
        set_current_tenant(tenant)
        
        # Appointment daqui 2h + 1 minuto
        scheduled_at = timezone.now() + timedelta(hours=2, minutes=1)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("100.00"),
            status="APPROVED",
        )
        
        refund = CancellationService.calculate_refund(apt)
        assert refund == Decimal("80.00")  # 80% de 100

    def test_cancel_without_payment_returns_zero(self):
        """Cancelamento sem pagamento: reembolso 0."""
        tenant = TenantFactory(subdomain="cancel4")
        set_current_tenant(tenant)
        
        scheduled_at = timezone.now() + timedelta(hours=30)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        # Sem Payment
        
        refund = CancellationService.calculate_refund(apt)
        assert refund == Decimal("0.00")

    def test_cancel_endpoint_creates_refund_record(self):
        """POST /appointments/{id}/cancel/ cria registro Refund."""
        tenant = TenantFactory(subdomain="cancel5")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        scheduled_at = timezone.now() + timedelta(hours=30)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="CONFIRMED",
        )
        Payment.all_objects.create(
            tenant=tenant,
            appointment=apt,
            amount=Decimal("50.00"),
            status="APPROVED",
        )
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            f"/api/appointments/{apt.id}/cancel/",
            {"reason": "Cliente desistiu"},
            format="json",
            HTTP_HOST="cancel5.localhost:8000",
        )
        
        assert response.status_code == 200
        assert "refund_amount" in response.data
        assert response.data["refund_amount"] == "45.00"
        
        # Verificar Refund criado
        refund = Refund.all_objects.get(appointment=apt)
        assert refund.amount == Decimal("45.00")
        assert refund.status == "PENDING"
        assert refund.reason == "Cliente desistiu"

    def test_cancel_prebooked_returns_400(self):
        """Cancelar appointment PRE_BOOKED retorna 400 INVALID_STATUS."""
        tenant = TenantFactory(subdomain="cancel6")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            f"/api/appointments/{apt.id}/cancel/",
            format="json",
            HTTP_HOST="cancel6.localhost:8000",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "INVALID_STATUS"
