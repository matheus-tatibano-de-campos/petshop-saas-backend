from django.http import JsonResponse
from rest_framework import generics, permissions, viewsets
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from rest_framework.response import Response

from decimal import Decimal

from django.conf import settings

from .serializers import (
    CheckoutSerializer,
    CustomTokenObtainPairSerializer,
    CustomerSerializer,
    PetSerializer,
    PreBookAppointmentSerializer,
    ServiceSerializer,
    TenantSerializer,
)
from .models import Appointment, Customer, Payment, Pet, Service
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
                "expires_at": appointment.expires_at.isoformat() if appointment.expires_at else None,
                "status": appointment.status,
            },
            status=201,
        )


class CheckoutView(generics.CreateAPIView):
    """POST /payments/checkout - creates payment and returns Mercado Pago link."""

    serializer_class = CheckoutSerializer
    permission_classes = [IsOwnerOrAttendant]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        appointment_id = serializer.validated_data["appointment_id"]
        appointment = Appointment.objects.get(pk=appointment_id)
        
        # Calculate 50% of service price
        amount = Decimal(str(appointment.service.price)) * Decimal("0.5")
        
        # Create Payment record
        payment = Payment.objects.create(
            appointment=appointment,
            amount=amount,
            status="PENDING",
        )
        
        # Create Mercado Pago preference
        try:
            import mercadopago
            
            sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
            preference_data = {
                "items": [
                    {
                        "title": f"{appointment.service.name} - {appointment.pet.name}",
                        "quantity": 1,
                        "unit_price": float(amount),
                    }
                ]
            }
            preference_response = sdk.preference().create(preference_data)
            preference = preference_response.get("response", {})
            
            if not preference or "id" not in preference:
                raise Exception("Failed to create Mercado Pago preference")
            
            # Save external payment ID
            payment.payment_id_external = preference["id"]
            payment.save()
            
            return Response(
                {"payment_link": preference.get("init_point")},
                status=201,
            )
        except Exception as e:
            payment.delete()
            return Response(
                {"error": {"code": "PAYMENT_ERROR", "message": str(e)}},
                status=500,
            )
