"""
pytest configuration and shared fixtures for business rules tests.
"""
import pytest
from django.utils import timezone
from core.context import clear_current_tenant, set_current_tenant


@pytest.fixture(autouse=True)
def clear_tenant_context():
    """Clear tenant context before and after each test."""
    clear_current_tenant()
    yield
    clear_current_tenant()


@pytest.fixture
def freeze_time():
    """Helper to freeze time for deterministic tests."""
    return timezone.now()
