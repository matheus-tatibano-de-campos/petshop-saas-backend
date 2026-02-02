from django.db import models

from .context import get_current_tenant


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
