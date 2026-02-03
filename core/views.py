from django.http import JsonResponse
from rest_framework import generics, permissions, viewsets
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import (
    CustomTokenObtainPairSerializer,
    CustomerSerializer,
    TenantSerializer,
)
from .models import Customer
from .permissions import IsOwnerOrAttendant


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


class CustomerViewSet(viewsets.ModelViewSet):
    """CRUD for customers scoped by tenant."""

    serializer_class = CustomerSerializer
    permission_classes = [IsOwnerOrAttendant]

    def get_queryset(self):
        return Customer.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context
