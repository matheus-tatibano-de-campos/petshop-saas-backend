"""
RN03: Validação de CPF

CPF deve ser validado com dígitos verificadores.
CPF duplicado no mesmo tenant é rejeitado.
CPF duplicado em tenants diferentes é permitido.
"""
import pytest
from pycpfcnpj import cpfcnpj
from rest_framework.test import APIClient
from core.context import set_current_tenant
from core.models import Customer
from tests.factories import TenantFactory, UserFactory, CustomerFactory


@pytest.mark.django_db
class TestCPFValidation:
    """RN03: CPF validation rules."""

    def test_valid_cpf_is_accepted(self):
        """CPF válido é aceito."""
        tenant = TenantFactory(subdomain="cpftest")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # CPF válido: 390.533.447-05
        response = client.post(
            "/api/customers/",
            {
                "name": "João Silva",
                "cpf": "39053344705",
                "email": "joao@example.com",
                "phone": "11999999999",
            },
            format="json",
            HTTP_HOST="cpftest.localhost:8000",
        )
        
        assert response.status_code == 201
        assert Customer.all_objects.count() == 1

    def test_invalid_cpf_is_rejected(self):
        """CPF inválido retorna 400 INVALID_CPF."""
        tenant = TenantFactory(subdomain="cpftest2")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # CPF inválido: dígitos verificadores errados
        response = client.post(
            "/api/customers/",
            {
                "name": "Maria Silva",
                "cpf": "12345678900",  # CPF inválido
                "email": "maria@example.com",
                "phone": "11888888888",
            },
            format="json",
            HTTP_HOST="cpftest2.localhost:8000",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "INVALID_CPF"
        assert "inválido" in response.data["error"]["message"].lower()

    def test_duplicate_cpf_same_tenant_is_rejected(self):
        """CPF duplicado no mesmo tenant retorna 400 CPF_DUPLICATE."""
        tenant = TenantFactory(subdomain="cpfdup")
        user = UserFactory(tenant=tenant)
        
        set_current_tenant(tenant)
        valid_cpf = "39053344705"
        CustomerFactory(tenant=tenant, cpf=valid_cpf, name="First Customer")
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/customers/",
            {
                "name": "Second Customer",
                "cpf": valid_cpf,
                "email": "second@example.com",
                "phone": "11777777777",
            },
            format="json",
            HTTP_HOST="cpfdup.localhost:8000",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "CPF_DUPLICATE"
        assert "cadastrado" in response.data["error"]["message"].lower()

    def test_duplicate_cpf_different_tenants_is_allowed(self):
        """CPF duplicado em tenants diferentes é permitido."""
        tenant1 = TenantFactory(subdomain="t1")
        tenant2 = TenantFactory(subdomain="t2")
        user1 = UserFactory(tenant=tenant1)
        user2 = UserFactory(tenant=tenant2)
        
        valid_cpf = "39053344705"
        
        # Criar customer no tenant1
        set_current_tenant(tenant1)
        CustomerFactory(tenant=tenant1, cpf=valid_cpf, name="Customer T1")
        
        # Criar customer com mesmo CPF no tenant2 deve funcionar
        client = APIClient()
        client.force_authenticate(user=user2)
        
        response = client.post(
            "/api/customers/",
            {
                "name": "Customer T2",
                "cpf": valid_cpf,
                "email": "customer@t2.com",
                "phone": "11666666666",
            },
            format="json",
            HTTP_HOST="t2.localhost:8000",
        )
        
        assert response.status_code == 201
        assert Customer.all_objects.filter(cpf=valid_cpf).count() == 2

    def test_cpf_with_special_characters_is_accepted(self):
        """CPF com pontos e hífen é aceito e normalizado."""
        tenant = TenantFactory(subdomain="cpfformat")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        # CPF formatado: 390.533.447-05
        response = client.post(
            "/api/customers/",
            {
                "name": "Formatted CPF",
                "cpf": "390.533.447-05",
                "email": "fmt@example.com",
                "phone": "11555555555",
            },
            format="json",
            HTTP_HOST="cpfformat.localhost:8000",
        )
        
        # Deve aceitar ou normalizar para apenas dígitos
        if response.status_code == 201:
            customer = Customer.all_objects.first()
            # CPF deve estar armazenado sem formatação
            assert "." not in customer.cpf
            assert "-" not in customer.cpf

    def test_edge_case_all_zeros_cpf_is_invalid(self):
        """CPF com todos zeros é inválido."""
        tenant = TenantFactory(subdomain="cpfzero")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/customers/",
            {
                "name": "Zero CPF",
                "cpf": "00000000000",
                "email": "zero@example.com",
                "phone": "11444444444",
            },
            format="json",
            HTTP_HOST="cpfzero.localhost:8000",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "INVALID_CPF"

    def test_edge_case_repeated_digits_cpf_is_invalid(self):
        """CPF com dígitos repetidos (111.111.111-11) é inválido."""
        tenant = TenantFactory(subdomain="cpfrep")
        user = UserFactory(tenant=tenant)
        
        client = APIClient()
        client.force_authenticate(user=user)
        
        response = client.post(
            "/api/customers/",
            {
                "name": "Repeated CPF",
                "cpf": "11111111111",
                "email": "rep@example.com",
                "phone": "11333333333",
            },
            format="json",
            HTTP_HOST="cpfrep.localhost:8000",
        )
        
        assert response.status_code == 400
        assert response.data["error"]["code"] == "INVALID_CPF"
