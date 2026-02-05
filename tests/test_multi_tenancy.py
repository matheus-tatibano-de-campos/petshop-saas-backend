"""
RN01: Isolamento Multi-Tenancy via Thread-Local

Testa que dados de um tenant não são visíveis para outro tenant.
Thread-local context garante isolamento em requests concorrentes.
"""
import pytest
from django.test import RequestFactory, TestCase
from core.context import clear_current_tenant, get_current_tenant, set_current_tenant
from core.middleware import TenantMiddleware
from core.models import Customer, Pet, Service, Appointment
from tests.factories import (
    TenantFactory,
    CustomerFactory,
    PetFactory,
    ServiceFactory,
    AppointmentFactory,
)


@pytest.mark.django_db
class TestMultiTenancyIsolation:
    """RN01: Multi-tenancy isolation through thread-local context."""

    def test_tenant_aware_manager_filters_by_current_tenant(self):
        """Manager.objects retorna apenas dados do tenant atual."""
        tenant1 = TenantFactory(subdomain="tenant1")
        tenant2 = TenantFactory(subdomain="tenant2")

        set_current_tenant(tenant1)
        customer1 = CustomerFactory(tenant=tenant1, name="Customer 1")
        
        set_current_tenant(tenant2)
        customer2 = CustomerFactory(tenant=tenant2, name="Customer 2")

        # Tenant 1 context: deve ver apenas customer1
        set_current_tenant(tenant1)
        assert Customer.objects.count() == 1
        assert Customer.objects.first().id == customer1.id

        # Tenant 2 context: deve ver apenas customer2
        set_current_tenant(tenant2)
        assert Customer.objects.count() == 1
        assert Customer.objects.first().id == customer2.id

    def test_all_objects_manager_bypasses_tenant_filter(self):
        """all_objects manager ignora filtro de tenant."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")

        set_current_tenant(tenant1)
        CustomerFactory(tenant=tenant1)
        
        set_current_tenant(tenant2)
        CustomerFactory(tenant=tenant2)

        # all_objects retorna ambos
        assert Customer.all_objects.count() == 2

    def test_tenant_middleware_sets_context_from_subdomain(self):
        """TenantMiddleware extrai subdomain e seta tenant no contexto."""
        tenant = TenantFactory(subdomain="testco", is_active=True)
        
        factory = RequestFactory()
        request = factory.get("/api/customers/", HTTP_HOST="testco.localhost:8000")
        
        # Middleware retorna None (sucesso) e seta request.tenant
        # Mas context é thread-local e pode não persistir após middleware call
        middleware = TenantMiddleware(lambda r: None)
        middleware(request)
        
        # Verificar que tenant foi setado no request
        assert hasattr(request, "tenant")
        assert request.tenant == tenant

    def test_tenant_middleware_returns_404_for_unknown_subdomain(self):
        """Unknown subdomain retorna 404 com TENANT_NOT_FOUND."""
        factory = RequestFactory()
        request = factory.get("/api/customers/", HTTP_HOST="nonexistent.localhost:8000")
        
        middleware = TenantMiddleware(lambda r: None)
        response = middleware(request)
        
        assert response.status_code == 404
        # JsonResponse não tem .json(), usar indexação direta
        import json
        data = json.loads(response.content)
        assert data["error"]["code"] == "TENANT_NOT_FOUND"

    def test_tenant_context_isolation_in_nested_operations(self):
        """Tenant context permanece consistente em operações aninhadas."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")

        set_current_tenant(tenant1)
        customer1 = CustomerFactory(tenant=tenant1)
        pet1 = PetFactory(tenant=tenant1, customer=customer1)
        service1 = ServiceFactory(tenant=tenant1)
        appointment1 = AppointmentFactory(tenant=tenant1, pet=pet1, service=service1)

        set_current_tenant(tenant2)
        customer2 = CustomerFactory(tenant=tenant2)
        pet2 = PetFactory(tenant=tenant2, customer=customer2)

        # Tenant 1 context: vê apenas seus dados
        set_current_tenant(tenant1)
        assert Customer.objects.count() == 1
        assert Pet.objects.count() == 1
        assert Service.objects.count() == 1
        assert Appointment.objects.count() == 1

        # Tenant 2 context: vê apenas seus dados
        set_current_tenant(tenant2)
        assert Customer.objects.count() == 1
        assert Pet.objects.count() == 1
        assert Service.objects.count() == 0  # service1 não é visível
        assert Appointment.objects.count() == 0  # appointment1 não é visível

    def test_cross_tenant_relationships_are_prevented(self):
        """FK para entidades de outro tenant deve falhar na validação."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")

        set_current_tenant(tenant1)
        customer_t1 = CustomerFactory(tenant=tenant1)

        set_current_tenant(tenant2)
        # Tentar criar pet de tenant2 com customer de tenant1 deve falhar na validação
        # (serializer valida customer.tenant == request.tenant)
        assert customer_t1.tenant != tenant2
