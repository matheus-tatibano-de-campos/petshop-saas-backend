from datetime import timedelta

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from .context import get_current_tenant


class UserManager(BaseUserManager):
    """Custom manager for User with email as username."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom User with email login and role."""

    ROLE_CHOICES = [
        ("OWNER", "Dono"),
        ("ATTENDANT", "Atendente"),
    ]

    username = None  # Remove username field
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="ATTENDANT")
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.CASCADE, null=True, blank=True
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class TenantAwareManager(models.Manager):
    """Manager that filters querysets by the current tenant."""

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant:
            return qs.filter(tenant=tenant)
        return qs.none()


class TenantAwareModel(models.Model):
    """
    Abstract base for models that belong to a tenant.
    Auto-sets tenant from thread-local context on save.
    Use TenantAwareManager for automatic tenant filtering.
    """

    tenant = models.ForeignKey(
        "Tenant", on_delete=models.CASCADE
    )
    objects = TenantAwareManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            tenant = get_current_tenant()
            if not tenant:
                raise ValueError("Tenant required. Set tenant or ensure TenantMiddleware has run.")
            self.tenant = tenant
        super().save(*args, **kwargs)


class Tenant(models.Model):
    name = models.CharField(max_length=100)
    subdomain = models.CharField(max_length=63, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.subdomain


class Customer(TenantAwareModel):
    """Customer linked to tenant with CPF uniqueness per tenant."""

    name = models.CharField(max_length=200)
    cpf = models.CharField(max_length=11)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("cpf", "tenant")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.cpf})"


class Pet(TenantAwareModel):
    """Pet linked to a customer. Cascade delete when customer is removed."""

    SPECIES_CHOICES = [
        ("DOG", "Cachorro"),
        ("CAT", "Gato"),
        ("OTHER", "Outro"),
    ]

    name = models.CharField(max_length=200)
    species = models.CharField(max_length=10, choices=SPECIES_CHOICES)
    breed = models.CharField(max_length=100)
    birth_date = models.DateField(null=True, blank=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="pets"
    )

    def __str__(self):
        return f"{self.name} ({self.get_species_display()})"


class Service(TenantAwareModel):
    """Service with price and duration. AC: price (Decimal), duration (int minutes)."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Appointment(TenantAwareModel):
    """Appointment: pet, service, scheduled_at. end_time computed from service duration."""

    STATUS_CHOICES = [
        ("PRE_BOOKED", "Pré-agendado"),
        ("CONFIRMED", "Confirmado"),
    ]

    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="appointments")
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="appointments")
    scheduled_at = models.DateTimeField()
    end_time = models.DateTimeField(editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PRE_BOOKED")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"{self.pet} - {self.service} @ {self.scheduled_at}"

    def save(self, *args, **kwargs):
        if self.scheduled_at and self.service_id:
            self.end_time = self.scheduled_at + timedelta(minutes=self.service.duration_minutes)
        super().save(*args, **kwargs)
