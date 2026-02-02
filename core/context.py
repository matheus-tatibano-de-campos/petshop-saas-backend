"""
Thread-local context for current tenant.
Used by TenantAwareModel to get tenant without accessing request directly.
"""
import threading

_thread_locals = threading.local()


def get_current_tenant():
    """Return the tenant for the current request thread, or None."""
    return getattr(_thread_locals, "tenant", None)


def set_current_tenant(tenant):
    """Set the tenant for the current request thread."""
    _thread_locals.tenant = tenant


def clear_current_tenant():
    """Clear the tenant from the current request thread."""
    if hasattr(_thread_locals, "tenant"):
        del _thread_locals.tenant
