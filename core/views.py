from django.http import JsonResponse
from rest_framework import generics, permissions, viewsets
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from rest_framework.response import Response

from .serializers import (
    CustomTokenObtainPairSerializer,
    CustomerSerializer,
    PetSerializer,
    PreBookAppointmentSerializer,
    ServiceSerializer,
    TenantSerializer,
)
from .models import Customer, Pet, Service
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


class PetViewSet(viewsets.ModelViewSet):
    """CRUD for pets. GET/POST /pets, GET/PUT/DELETE /pets/{id}. Pet must be linked to customer in same tenant."""

    serializer_class = PetSerializer
    permission_classes = [IsOwnerOrAttendant]

    def get_queryset(self):
        return Pet.objects.all()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class ServiceViewSet(viewsets.ModelViewSet):
    """CRUD for services. Filter ?is_active=true|false. Validates price >= 0, duration_minutes > 0."""

    serializer_class = ServiceSerializer
    permission_classes = [IsOwnerOrAttendant]

    def get_queryset(self):
        qs = Service.objects.all()
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class PreBookAppointmentView(generics.CreateAPIView):
    """POST /appointments/pre-book - creates appointment with status=PRE_BOOKED."""

    serializer_class = PreBookAppointmentSerializer
    permission_classes = [IsOwnerOrAttendant]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save()
        return Response(
            {
                "appointment_id": appointment.id,
                "end_time": appointment.end_time.isoformat() if appointment.end_time else None,
                "status": appointment.status,
            },
            status=201,
        )
