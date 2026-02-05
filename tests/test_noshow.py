"""
RN08: No-Show

Appointments CONFIRMED podem ser marcados como NO_SHOW.
Transição válida: CONFIRMED → NO_SHOW.
Transição inválida de outros status retorna 422 INVALID_TRANSITION.
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.services import AppointmentService, InvalidTransitionError
from tests.factories import TenantFactory, UserFactory, AppointmentFactory


@pytest.mark.django_db
class TestNoShow:
    """RN08: No-show transition rules."""

    def test_confirmed_to_noshow_is_valid(self):
        """CONFIRMED → NO_SHOW é transição válida."""
        tenant = TenantFactory(subdomain="noshow1")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="CONFIRMED")
        
        AppointmentService.transition(apt, "NO_SHOW")
        
        apt.refresh_from_db()
        assert apt.status == "NO_SHOW"

    def test_prebooked_to_noshow_is_invalid(self):
        """PRE_BOOKED → NO_SHOW é transição inválida."""
        tenant = TenantFactory(subdomain="noshow2")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        
        with pytest.raises(InvalidTransitionError):
            AppointmentService.transition(apt, "NO_SHOW")
        
        apt.refresh_from_db()
        assert apt.status == "PRE_BOOKED"  # Não mudou

    def test_noshow_via_api_returns_200(self):
        """PATCH /appointments/{id}/ com status=NO_SHOW retorna 200."""
        tenant = TenantFactory(subdomain="noshow3")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="CONFIRMED")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.patch(
            f"/api/appointments/{apt.id}/",
            {"status": "NO_SHOW"},
            format="json",
            HTTP_HOST="noshow3.localhost:8000",
        )
        
        assert response.status_code == 200
        
        apt.refresh_from_db()
        assert apt.status == "NO_SHOW"

    def test_prebooked_to_noshow_via_api_returns_422(self):
        """PATCH PRE_BOOKED→NO_SHOW via API retorna 422 INVALID_TRANSITION."""
        tenant = TenantFactory(subdomain="noshow4")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="PRE_BOOKED")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.patch(
            f"/api/appointments/{apt.id}/",
            {"status": "NO_SHOW"},
            format="json",
            HTTP_HOST="noshow4.localhost:8000",
        )
        
        assert response.status_code == 422
        assert response.data["error"]["code"] == "INVALID_TRANSITION"
        assert "PRE_BOOKED" in response.data["error"]["message"]
        assert "NO_SHOW" in response.data["error"]["message"]

    def test_noshow_is_terminal_state(self):
        """NO_SHOW → qualquer outro status é inválido."""
        tenant = TenantFactory(subdomain="noshow5")
        set_current_tenant(tenant)
        
        apt = AppointmentFactory(tenant=tenant, status="NO_SHOW")
        
        with pytest.raises(InvalidTransitionError):
            AppointmentService.transition(apt, "COMPLETED")
        
        with pytest.raises(InvalidTransitionError):
            AppointmentService.transition(apt, "CONFIRMED")

    def test_confirmed_has_multiple_valid_transitions_including_noshow(self):
        """CONFIRMED tem múltiplas transições válidas: COMPLETED, NO_SHOW, CANCELLED."""
        tenant = TenantFactory(subdomain="noshow6")
        set_current_tenant(tenant)
        
        allowed = AppointmentService.get_allowed_transitions("CONFIRMED")
        
        assert "COMPLETED" in allowed
        assert "NO_SHOW" in allowed
        assert "CANCELLED" in allowed
        assert len(allowed) == 3
