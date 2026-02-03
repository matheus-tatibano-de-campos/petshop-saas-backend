from pycpfcnpj import cpfcnpj
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Customer, Pet, Tenant


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT serializer that includes tenant_id in the token payload."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token["tenant_id"] = user.tenant_id
        token["role"] = user.role
        token["email"] = user.email
        return token


class TenantSerializer(serializers.ModelSerializer):
    """Serializer used to onboard new tenants (superuser only)."""

    class Meta:
        model = Tenant
        fields = ["id", "name", "subdomain", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class CustomerSerializer(serializers.ModelSerializer):
    """Serializer for Customer CRUD with CPF validation."""

    class Meta:
        model = Customer
        fields = ["id", "name", "cpf", "email", "phone", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_cpf(self, value):
        digits = "".join(filter(str.isdigit, value or ""))
        if len(digits) != 11 or not cpfcnpj.validate(digits):
            raise serializers.ValidationError("CPF inválido.")
        return digits

    def validate(self, attrs):
        attrs = super().validate(attrs)
        tenant = self.context["request"].tenant
        cpf = attrs.get("cpf") or (self.instance and self.instance.cpf)
        if cpf:
            qs = Customer.objects.filter(cpf=cpf, tenant=tenant)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({"cpf": "CPF já cadastrado neste tenant."})
        return attrs

    def create(self, validated_data):
        tenant = self.context["request"].tenant
        return Customer.objects.create(tenant=tenant, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("tenant", None)
        return super().update(instance, validated_data)


class PetSerializer(serializers.ModelSerializer):
    """Serializer for Pet CRUD. Validates customer_id exists and belongs to same tenant."""

    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.all_objects.all(),
        allow_null=False,
    )

    class Meta:
        model = Pet
        fields = ["id", "name", "species", "breed", "birth_date", "customer"]
        read_only_fields = ["id"]

    def validate_customer(self, value):
        """Ensure customer belongs to request tenant (CUSTOMER_WRONG_TENANT if not)."""
        request = self.context.get("request")
        if not request or not hasattr(request, "tenant"):
            return value
        tenant = request.tenant
        if value.tenant_id != tenant.id:
            raise serializers.ValidationError("Customer pertence a outro tenant")
        return value

    def create(self, validated_data):
        tenant = self.context["request"].tenant
        return Pet.objects.create(tenant=tenant, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("tenant", None)
        return super().update(instance, validated_data)
