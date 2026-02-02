from django.http import JsonResponse

from .context import clear_current_tenant, set_current_tenant
from .models import Tenant


class TenantMiddleware:
    """
    Resolves tenant from subdomain and sets it in thread-local context.
    Returns 404 with standard error format if tenant not found.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        if host in ("127.0.0.1", "localhost"):
            subdomain = "localhost"
        else:
            subdomain = host.split(".")[0]

        tenant = Tenant.objects.filter(
            subdomain=subdomain, is_active=True
        ).first()

        if tenant is None:
            return JsonResponse(
                {"error": {"code": "TENANT_NOT_FOUND", "message": "Tenant não encontrado"}},
                status=404,
            )

        set_current_tenant(tenant)
        request.tenant = tenant

        try:
            response = self.get_response(request)
        finally:
            clear_current_tenant()

        return response
