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
