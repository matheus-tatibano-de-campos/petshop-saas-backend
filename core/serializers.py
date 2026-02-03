from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Tenant


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
