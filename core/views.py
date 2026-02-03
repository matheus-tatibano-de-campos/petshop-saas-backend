from django.http import JsonResponse
from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .permissions import IsOwner
from .serializers import (
    CustomTokenObtainPairSerializer,
    TenantSerializer,
)


def health(request):
    """Health check endpoint - returns 200 OK."""
    return JsonResponse({"status": "ok"})


def tenant_info(request):
    """Returns current tenant info (for tests and debugging)."""
    return JsonResponse({
        "tenant_id": request.tenant.id,
        "subdomain": request.tenant.subdomain,
    })


class LoginView(TokenObtainPairView):
    """POST /auth/login - returns access and refresh tokens with tenant_id."""
    serializer_class = CustomTokenObtainPairSerializer


class RefreshTokenView(TokenRefreshView):
    """POST /auth/refresh - returns new access token."""
    pass


class TenantCreateView(generics.CreateAPIView):
    """Endpoint to create new tenants (superuser only)."""

    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAdminUser]
