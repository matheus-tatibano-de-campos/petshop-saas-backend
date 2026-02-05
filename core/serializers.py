from datetime import timedelta

from django.db import models
from pycpfcnpj import cpfcnpj
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .exceptions import AppointmentConflictError
from .models import Appointment, Customer, Payment, Pet, Service, Tenant
from .services import AppointmentService


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


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer for Service CRUD. Validates price >= 0, duration_minutes > 0."""

    class Meta:
        model = Service
        fields = ["id", "name", "description", "price", "duration_minutes", "is_active"]
        read_only_fields = ["id"]

    def validate_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Preço deve ser maior ou igual a zero")
        return value

    def validate_duration_minutes(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError("Duração deve ser maior que zero")
        return value

    def create(self, validated_data):
        tenant = self.context["request"].tenant
        return Service.objects.create(tenant=tenant, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("tenant", None)
        return super().update(instance, validated_data)


class PreBookAppointmentSerializer(serializers.Serializer):
    """Serializer for POST /appointments/pre-book/. Validates pet and service exist in tenant."""

    pet_id = serializers.IntegerField()
    service_id = serializers.IntegerField()
    scheduled_at = serializers.DateTimeField()

    def validate_pet_id(self, value):
        request = self.context.get("request")
        if not request or not hasattr(request, "tenant"):
            return value
        tenant = request.tenant
        try:
            pet = Pet.objects.get(pk=value)
        except Pet.DoesNotExist:
            raise serializers.ValidationError("Pet não encontrado")
        if pet.tenant_id != tenant.id:
            raise serializers.ValidationError("Pet pertence a outro tenant")
        return value

    def validate_service_id(self, value):
        request = self.context.get("request")
        if not request or not hasattr(request, "tenant"):
            return value
        tenant = request.tenant
        try:
            service = Service.objects.get(pk=value)
        except Service.DoesNotExist:
            raise serializers.ValidationError("Serviço não encontrado")
        if service.tenant_id != tenant.id:
            raise serializers.ValidationError("Serviço pertence a outro tenant")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get("request")
        if not request or not hasattr(request, "tenant"):
            return attrs
        pet_id = attrs["pet_id"]
        service_id = attrs["service_id"]
        scheduled_at = attrs["scheduled_at"]
        service = Service.objects.get(pk=service_id)
        end_time = scheduled_at + timedelta(minutes=service.duration_minutes)
        overlapping = Appointment.objects.filter(
            models.Q(pet_id=pet_id) | models.Q(service_id=service_id)
        ).exclude(status__in=["CANCELLED", "EXPIRED"]).filter(
            scheduled_at__lt=end_time,
            end_time__gt=scheduled_at,
        )
        if overlapping.exists():
            raise AppointmentConflictError("Horário já ocupado")
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        tenant = request.tenant
        pet = Pet.objects.get(pk=validated_data["pet_id"])
        service = Service.objects.get(pk=validated_data["service_id"])
        scheduled_at = validated_data["scheduled_at"]
        return Appointment.objects.create(
            tenant=tenant,
            pet=pet,
            service=service,
            scheduled_at=scheduled_at,
            status="PRE_BOOKED",
        )


class CheckoutSerializer(serializers.Serializer):
    """Serializer for POST /payments/checkout/. Validates appointment_id and status=PRE_BOOKED."""

    appointment_id = serializers.IntegerField()

    def validate_appointment_id(self, value):
        request = self.context.get("request")
        if not request or not hasattr(request, "tenant"):
            return value
        tenant = request.tenant
        try:
            appointment = Appointment.all_objects.get(pk=value)
        except Appointment.DoesNotExist:
            raise serializers.ValidationError("Appointment não encontrado")
        if appointment.tenant_id != tenant.id:
            raise serializers.ValidationError("Appointment pertence a outro tenant")
        if appointment.status != "PRE_BOOKED":
            raise serializers.ValidationError("Appointment deve estar PRE_BOOKED")
        return value


class CancelAppointmentSerializer(serializers.Serializer):
    """Request body for POST /appointments/{id}/cancel/. Optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AppointmentSerializer(serializers.ModelSerializer):
    """Serializer for Appointment. Status updates use AppointmentService.transition()."""

    class Meta:
        model = Appointment
        fields = ["id", "pet", "service", "scheduled_at", "end_time", "status", "expires_at", "created_at", "updated_at"]
        read_only_fields = ["id", "end_time", "created_at", "updated_at"]

    def update(self, instance, validated_data):
        new_status = validated_data.pop("status", None)
        if new_status is not None and new_status != instance.status:
            AppointmentService.transition(instance, new_status)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if validated_data:
            instance.save()
        return instance
