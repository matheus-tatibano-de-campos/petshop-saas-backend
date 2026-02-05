"""
Custom API exceptions with standardized codes for error responses.
All exceptions have a `code` attribute used in {"error": {"code": "...", "message": "..."}}.
"""


class APIError(Exception):
    """Base exception for API errors with code and message."""

    code = "API_ERROR"

    def __init__(self, message, code=None):
        self._message = message
        if code is not None:
            self.code = code
        super().__init__(message)


class InvalidCPFError(APIError):
    """Raised when CPF validation fails."""

    code = "INVALID_CPF"

    def __init__(self, message="CPF inválido."):
        super().__init__(message)


class AppointmentConflictError(APIError):
    """Raised when appointment scheduling conflicts with existing appointments."""

    code = "CONFLICT_SCHEDULE"

    def __init__(self, message="Conflito de horário"):
        super().__init__(message)


class InvalidTransitionError(APIError):
    """Raised when an invalid appointment status transition is attempted."""

    code = "INVALID_TRANSITION"

    def __init__(self, current_status, new_status, allowed_transitions):
        self.current_status = current_status
        self.new_status = new_status
        self.allowed_transitions = allowed_transitions
        message = (
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed transitions: {allowed_transitions}"
        )
        super().__init__(message)


class PaymentFailedError(APIError):
    """Raised when payment processing fails."""

    code = "PAYMENT_FAILED"

    def __init__(self, message="Falha no pagamento"):
        super().__init__(message)


class TenantNotFoundError(APIError):
    """Raised when tenant cannot be resolved from request."""

    code = "TENANT_NOT_FOUND"

    def __init__(self, message="Tenant não encontrado"):
        super().__init__(message)
