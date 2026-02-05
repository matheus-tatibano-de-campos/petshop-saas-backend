"""
RN04: Conflito de Agendamentos

Appointments não podem se sobrepor para o mesmo tenant.
Exclusion constraint: (tenant, tstzrange(scheduled_at, end_time)) no PostgreSQL.
CANCELLED e EXPIRED não bloqueiam slots.
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import Appointment
from tests.factories import (
    TenantFactory,
    UserFactory,
    PetFactory,
    ServiceFactory,
    AppointmentFactory,
)


@pytest.mark.django_db
class TestAppointmentConflict:
    """RN04: Appointment overlap detection."""

    def test_overlapping_appointments_are_rejected(self):
        """Appointments sobrepostos para mesmo tenant retornam 409 CONFLICT_SCHEDULE."""
        tenant = TenantFactory(subdomain="conflict1")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant, duration_minutes=60)
        
        # Criar primeiro appointment: 14:00-15:00
        scheduled_at = timezone.now() + timedelta(days=1, hours=14 - timezone.now().hour)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        r1 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at.isoformat(),
            },
            format="json",
            HTTP_HOST="conflict1.localhost:8000",
        )
        assert r1.status_code == 201
        
        # Tentar criar segundo appointment sobreposto: 14:30-15:30
        overlapping_time = scheduled_at + timedelta(minutes=30)
        r2 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": overlapping_time.isoformat(),
            },
            format="json",
            HTTP_HOST="conflict1.localhost:8000",
        )
        
        assert r2.status_code == 409
        assert r2.data["error"]["code"] == "CONFLICT_SCHEDULE"

    def test_edge_case_appointments_touching_at_boundary_are_allowed(self):
        """Appointments que se tocam exatamente no limite (15:00-16:00, 16:00-17:00) são permitidos."""
        tenant = TenantFactory(subdomain="touch")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant, duration_minutes=60)
        
        base_time = timezone.now() + timedelta(days=1)
        scheduled_at1 = base_time.replace(hour=15, minute=0, second=0, microsecond=0)
        scheduled_at2 = scheduled_at1 + timedelta(hours=1)  # 16:00
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        r1 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at1.isoformat(),
            },
            format="json",
            HTTP_HOST="touch.localhost:8000",
        )
        assert r1.status_code == 201
        
        r2 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at2.isoformat(),
            },
            format="json",
            HTTP_HOST="touch.localhost:8000",
        )
        # Deve ser permitido (range [15:00, 16:00) não sobrepõe [16:00, 17:00))
        assert r2.status_code == 201

    def test_edge_case_overlap_by_one_second_is_detected(self):
        """Overlap de 1 segundo é detectado."""
        tenant = TenantFactory(subdomain="onesec")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant, duration_minutes=60)
        
        base_time = timezone.now() + timedelta(days=1)
        scheduled_at1 = base_time.replace(hour=14, minute=0, second=0, microsecond=0)
        # 1 segundo antes do fim: 14:59:59
        scheduled_at2 = scheduled_at1 + timedelta(minutes=59, seconds=59)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        r1 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at1.isoformat(),
            },
            format="json",
            HTTP_HOST="onesec.localhost:8000",
        )
        assert r1.status_code == 201
        
        r2 = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at2.isoformat(),
            },
            format="json",
            HTTP_HOST="onesec.localhost:8000",
        )
        assert r2.status_code == 409

    def test_cancelled_appointment_does_not_block_slot(self):
        """Appointment CANCELLED não bloqueia o horário."""
        tenant = TenantFactory(subdomain="cancel")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant, duration_minutes=60)
        
        scheduled_at = timezone.now() + timedelta(days=1, hours=10 - timezone.now().hour)
        
        # Criar e cancelar appointment
        apt = AppointmentFactory(
            tenant=tenant,
            pet=pet,
            service=service,
            scheduled_at=scheduled_at,
            status="CANCELLED",
        )
        
        # Tentar criar novo appointment no mesmo horário deve funcionar
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at.isoformat(),
            },
            format="json",
            HTTP_HOST="cancel.localhost:8000",
        )
        assert response.status_code == 201

    def test_expired_appointment_does_not_block_slot(self):
        """Appointment EXPIRED não bloqueia o horário."""
        tenant = TenantFactory(subdomain="expire")
        user = UserFactory(tenant=tenant)
        set_current_tenant(tenant)
        
        pet = PetFactory(tenant=tenant)
        service = ServiceFactory(tenant=tenant, duration_minutes=60)
        
        scheduled_at = timezone.now() + timedelta(days=1, hours=11 - timezone.now().hour)
        
        # Criar appointment expirado
        apt = AppointmentFactory(
            tenant=tenant,
            pet=pet,
            service=service,
            scheduled_at=scheduled_at,
            status="EXPIRED",
        )
        
        # Tentar criar novo appointment no mesmo horário deve funcionar
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet.id,
                "service_id": service.id,
                "scheduled_at": scheduled_at.isoformat(),
            },
            format="json",
            HTTP_HOST="expire.localhost:8000",
        )
        assert response.status_code == 201

    def test_different_tenants_can_overlap(self):
        """Appointments de tenants diferentes podem sobrepor horários."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")
        user1 = UserFactory(tenant=tenant1)
        user2 = UserFactory(tenant=tenant2)
        
        scheduled_at = timezone.now() + timedelta(days=1, hours=12 - timezone.now().hour)
        
        # Criar appointment no tenant1
        set_current_tenant(tenant1)
        pet1 = PetFactory(tenant=tenant1)
        service1 = ServiceFactory(tenant=tenant1, duration_minutes=60)
        
        client1 = APIClient()
        client1.force_authenticate(user=user1)
        r1 = client1.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet1.id,
                "service_id": service1.id,
                "scheduled_at": scheduled_at.isoformat(),
            },
            format="json",
            HTTP_HOST="t1.localhost:8000",
        )
        assert r1.status_code == 201
        
        # Criar appointment no tenant2 no MESMO horário deve funcionar
        set_current_tenant(tenant2)
        pet2 = PetFactory(tenant=tenant2)
        service2 = ServiceFactory(tenant=tenant2, duration_minutes=60)
        
        client2 = APIClient()
        client2.force_authenticate(user=user2)
        r2 = client2.post(
            "/api/appointments/pre-book/",
            {
                "pet_id": pet2.id,
                "service_id": service2.id,
                "scheduled_at": scheduled_at.isoformat(),
            },
            format="json",
            HTTP_HOST="t2.localhost:8000",
        )
        assert r2.status_code == 201
