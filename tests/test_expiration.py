"""
RN05: Expiração de Pré-Agendamentos

PRE_BOOKED appointments expiram se não forem pagos antes de expires_at.
Command expire_prebookings marca como EXPIRED.
Slots expirados ficam disponíveis para novos bookings.
"""
import pytest
from datetime import timedelta
from django.core.management import call_command
from django.utils import timezone
from io import StringIO
from core.context import set_current_tenant
from core.models import Appointment
from tests.factories import TenantFactory, AppointmentFactory


@pytest.mark.django_db
class TestPreBookingExpiration:
    """RN05: PRE_BOOKED appointment expiration."""

    def test_prebook_appointment_has_expires_at(self):
        """Appointment PRE_BOOKED tem expires_at calculado automaticamente (default: now + 10min)."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        # scheduled_at no futuro
        scheduled_at = timezone.now() + timedelta(hours=24)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="PRE_BOOKED",
        )
        
        # expires_at deve existir (definido por model.save() ou default)
        assert apt.expires_at is not None
        # expires_at geralmente é now() + 10min, não scheduled_at - 10min
        # Verificar que está entre now e scheduled_at
        now = timezone.now()
        assert now <= apt.expires_at <= scheduled_at

    def test_expire_prebookings_command_marks_expired(self):
        """expire_prebookings marca PRE_BOOKED com expires_at < now como EXPIRED."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        # Appointment que já expirou
        past = timezone.now() - timedelta(minutes=15)
        apt_expired = AppointmentFactory(
            tenant=tenant,
            scheduled_at=timezone.now() + timedelta(hours=1),
            status="PRE_BOOKED",
            expires_at=past,
        )
        
        # Appointment que ainda não expirou
        future = timezone.now() + timedelta(hours=1)
        apt_valid = AppointmentFactory(
            tenant=tenant,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status="PRE_BOOKED",
            expires_at=future,
        )
        
        out = StringIO()
        call_command("expire_prebookings", stdout=out)
        
        apt_expired.refresh_from_db()
        apt_valid.refresh_from_db()
        
        assert apt_expired.status == "EXPIRED"
        assert apt_valid.status == "PRE_BOOKED"
        assert "1" in out.getvalue() or "expired" in out.getvalue().lower()

    def test_expired_appointment_frees_slot(self):
        """Appointment EXPIRED libera o slot para novo booking."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        scheduled_at = timezone.now() + timedelta(hours=24)
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="EXPIRED",
        )
        
        # Criar novo appointment no mesmo horário deve funcionar
        apt2 = AppointmentFactory(
            tenant=tenant,
            scheduled_at=scheduled_at,
            status="PRE_BOOKED",
        )
        
        assert Appointment.all_objects.filter(tenant=tenant).count() == 2

    def test_edge_case_expires_exactly_now(self):
        """Appointment que expira exatamente agora deve ser marcado como EXPIRED."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        # expires_at = now
        now = timezone.now()
        apt = AppointmentFactory(
            tenant=tenant,
            scheduled_at=now + timedelta(hours=1),
            status="PRE_BOOKED",
            expires_at=now,
        )
        
        call_command("expire_prebookings")
        
        apt.refresh_from_db()
        assert apt.status == "EXPIRED"

    def test_confirmed_appointments_are_not_expired(self):
        """Appointments CONFIRMED não são expirados pelo command."""
        tenant = TenantFactory()
        set_current_tenant(tenant)
        
        past = timezone.now() - timedelta(minutes=30)
        apt_confirmed = AppointmentFactory(
            tenant=tenant,
            scheduled_at=timezone.now() + timedelta(hours=1),
            status="CONFIRMED",
            expires_at=past,
        )
        
        call_command("expire_prebookings")
        
        apt_confirmed.refresh_from_db()
        assert apt_confirmed.status == "CONFIRMED"  # Não mudou
