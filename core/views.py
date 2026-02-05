import hashlib
import hmac
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db import transaction
from rest_framework import generics, permissions, viewsets
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from rest_framework.response import Response

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

from .serializers import (
    AppointmentSerializer,
    CancelAppointmentSerializer,
    CheckoutSerializer,
    CustomTokenObtainPairSerializer,
    CustomerSerializer,
    PetSerializer,
    PreBookAppointmentSerializer,
    ServiceSerializer,
    TenantSerializer,
)
from .models import Appointment, Customer, Payment, Pet, Refund, Service
from .permissions import IsOwnerOrAttendant
from .services import AppointmentService, CancellationService


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


class AppointmentViewSet(viewsets.ModelViewSet):
    """CRUD for appointments. PATCH status uses AppointmentService.transition (422 if invalid)."""

    serializer_class = AppointmentSerializer
    permission_classes = [IsOwnerOrAttendant]

    def get_queryset(self):
        return Appointment.objects.all()

    @extend_schema(
        request=CancelAppointmentSerializer,
        responses={200: {"description": "refund_amount"}},
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """
        POST /appointments/{id}/cancel - Cancel CONFIRMED appointment and calculate refund.
        Body (optional): {reason: string}
        Returns: {refund_amount}
        """
        appointment = self.get_object()

        if (appointment.status or "").strip() != "CONFIRMED":
            return Response(
                {"error": {"code": "INVALID_STATUS", "message": "Apenas appointments CONFIRMED podem ser cancelados"}},
                status=400,
            )

        reason = request.data.get("reason", "") or ""
        refund_amount = CancellationService.calculate_refund(appointment)

        AppointmentService.transition(appointment, "CANCELLED")

        Refund.objects.create(
            appointment=appointment,
            amount=refund_amount,
            status="PENDING",
            reason=reason[:255],
            tenant=appointment.tenant,
        )

        return Response({"refund_amount": str(refund_amount)}, status=200)


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
            
            logger.info(
                "Creating MP preference",
                extra={
                    "appointment_id": appointment.id,
                    "amount": float(amount),
                    "token_prefix": settings.MERCADOPAGO_ACCESS_TOKEN[:20],
                },
            )
            
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
            
            logger.info("Calling MP API", extra={"preference_data": preference_data})
            preference_response = sdk.preference().create(preference_data)
            logger.info("MP Response", extra={"response": preference_response})
            
            preference = preference_response.get("response", {})
            
            if not preference or "id" not in preference:
                error_msg = preference_response.get("message", "Failed to create Mercado Pago preference")
                logger.error("MP preference creation failed", extra={"response": preference_response})
                raise Exception(error_msg)
            
            # Save external payment ID
            payment.payment_id_external = preference["id"]
            payment.save()
            
            return Response(
                {"payment_link": preference.get("init_point")},
                status=201,
            )
        except Exception as e:
            logger.error(
                "Checkout error",
                extra={"error": str(e), "error_type": type(e).__name__},
                exc_info=True,
            )
            payment.delete()
            return Response(
                {"error": {"code": "PAYMENT_ERROR", "message": str(e)}},
                status=500,
            )


@method_decorator(csrf_exempt, name="dispatch")
class MercadoPagoWebhookView(APIView):
    """POST /webhooks/mercadopago - processes Mercado Pago payment notifications."""

    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        webhook_received_at = timezone.now()
        try:
            # Extract notification data
            data = request.data
            logger.info(
                "Webhook received",
                extra={"data": data, "timestamp": webhook_received_at.isoformat()}
            )

            # Get notification type
            notification_type = data.get("type")
            
            if notification_type != "payment":
                logger.warning(
                    "Ignoring non-payment notification",
                    extra={"type": notification_type},
                )
                return Response({"status": "ignored"}, status=200)

            # Extract payment ID from data
            payment_data = data.get("data", {})
            payment_id_external = payment_data.get("id")

            if not payment_id_external:
                logger.error("Missing payment ID in webhook", extra={"data": data})
                return Response(
                    {"error": {"code": "MISSING_PAYMENT_ID", "message": "Payment ID not found"}},
                    status=400,
                )

            # Find Payment in database
            try:
                payment = Payment.all_objects.get(payment_id_external=str(payment_id_external))
            except Payment.DoesNotExist:
                logger.warning(
                    "Payment not found for webhook",
                    extra={"payment_id_external": payment_id_external},
                )
                return Response(
                    {"error": {"code": "PAYMENT_NOT_FOUND", "message": "Payment not found"}},
                    status=404,
                )

            # Check if already processed (idempotency)
            if payment.webhook_processed:
                logger.info(
                    "Webhook already processed - idempotency check passed",
                    extra={
                        "payment_id": payment.id,
                        "payment_id_external": payment_id_external,
                        "timestamp": webhook_received_at.isoformat(),
                    },
                )
                return Response({"status": "already_processed"}, status=200)

            # Query Mercado Pago API for payment status
            try:
                import mercadopago

                sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
                payment_info = sdk.payment().get(payment_id_external)
                payment_response = payment_info.get("response", {})

                if not payment_response:
                    raise Exception("Empty response from Mercado Pago API")

                mp_status = payment_response.get("status")
                logger.info(
                    "Payment status from MP",
                    extra={
                        "payment_id": payment.id,
                        "payment_id_external": payment_id_external,
                        "mp_status": mp_status,
                        "timestamp": webhook_received_at.isoformat(),
                    },
                )

                # Update payment and appointment if approved (with transaction for atomicity)
                if mp_status == "approved":
                    with transaction.atomic():
                        # Re-fetch with select_for_update to lock the row
                        payment = Payment.all_objects.select_for_update().get(pk=payment.id)
                        
                        # Double-check if already processed (race condition protection)
                        if payment.webhook_processed:
                            logger.info(
                                "Payment already processed during transaction",
                                extra={"payment_id": payment.id},
                            )
                            return Response({"status": "already_processed"}, status=200)
                        
                        payment.status = "APPROVED"
                        payment.webhook_processed = True
                        payment.save()

                        appointment = payment.appointment
                        appointment.status = "CONFIRMED"
                        appointment.save()

                    logger.info(
                        "Payment approved and appointment confirmed",
                        extra={
                            "payment_id": payment.id,
                            "appointment_id": appointment.id,
                            "tenant_id": appointment.tenant_id,
                            "timestamp": webhook_received_at.isoformat(),
                        },
                    )

                    return Response({"status": "processed", "payment_status": "approved"}, status=200)
                    
                elif mp_status == "rejected":
                    with transaction.atomic():
                        # Re-fetch with select_for_update to lock the row
                        payment = Payment.all_objects.select_for_update().get(pk=payment.id)
                        
                        # Double-check if already processed
                        if payment.webhook_processed:
                            logger.info(
                                "Payment already processed during transaction",
                                extra={"payment_id": payment.id},
                            )
                            return Response({"status": "already_processed"}, status=200)
                        
                        payment.status = "REJECTED"
                        payment.webhook_processed = True
                        payment.save()

                    logger.info(
                        "Payment rejected",
                        extra={
                            "payment_id": payment.id,
                            "mp_status": mp_status,
                            "timestamp": webhook_received_at.isoformat(),
                        },
                    )

                    return Response({"status": "processed", "payment_status": "rejected"}, status=200)
                else:
                    logger.info(
                        "Payment status not final",
                        extra={"payment_id": payment.id, "mp_status": mp_status},
                    )
                    return Response({"status": "pending", "payment_status": mp_status}, status=200)

            except Exception as e:
                logger.error(
                    "Error querying Mercado Pago API",
                    extra={"payment_id": payment.id, "error": str(e)},
                    exc_info=True,
                )
                return Response(
                    {"error": {"code": "MP_API_ERROR", "message": str(e)}},
                    status=500,
                )

        except Exception as e:
            logger.error("Webhook processing error", extra={"error": str(e)}, exc_info=True)
            return Response(
                {"error": {"code": "WEBHOOK_ERROR", "message": str(e)}},
                status=500,
            )
