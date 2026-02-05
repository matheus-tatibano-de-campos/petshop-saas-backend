"""
Custom exception handler that returns all errors in the standard format:
{"error": {"code": "...", "message": "..."}}

Handles: ValidationError, IntegrityError, and custom API exceptions.
"""
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .exceptions import (
    APIError,
    InvalidCPFError,
    AppointmentConflictError,
    InvalidTransitionError,
    PaymentFailedError,
    TenantNotFoundError,
)


def _normalize_message(detail):
    """Extract a single message string from DRF error detail."""
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        parts = []
        for k, v in detail.items():
            msg = _normalize_message(v)
            parts.append(f"{k}: {msg}" if isinstance(v, dict) else msg)
        return " ".join(parts) if len(parts) == 1 else "; ".join(parts)
    if isinstance(detail, list):
        return "; ".join(_normalize_message(d) for d in detail)
    return str(detail)


def _infer_code(message):
    """Map common validation messages to error codes."""
    if not message:
        return "VALIDATION_ERROR"
    msg_lower = message.lower()
    if "cpf inválido" in msg_lower or "cpf invalido" in msg_lower:
        return "INVALID_CPF"
    if "cpf já cadastrado" in msg_lower or "cpf ja cadastrado" in msg_lower:
        return "CPF_DUPLICATE"
    if "customer pertence a outro tenant" in msg_lower:
        return "CUSTOMER_WRONG_TENANT"
    if "preço deve ser" in msg_lower:
        return "INVALID_PRICE"
    if "duração deve ser" in msg_lower:
        return "INVALID_DURATION"
    if "horário já ocupado" in msg_lower or "conflito" in msg_lower:
        return "CONFLICT_SCHEDULE"
    if "appointment" in msg_lower and "pre_booked" in msg_lower:
        return "INVALID_STATUS"
    return "VALIDATION_ERROR"


def _error_response(code, message, status=400):
    """Build standardized error response."""
    return Response(
        {"error": {"code": code, "message": message}},
        status=status,
    )


def custom_exception_handler(exc, context):
    """Convert all API errors to standard format."""
    # Custom API exceptions (have .code attribute)
    if isinstance(exc, APIError):
        if isinstance(exc, InvalidTransitionError):
            status = 422
        elif isinstance(exc, AppointmentConflictError):
            status = 409
        else:
            status = 400
        return _error_response(exc.code, str(exc), status=status)

    # IntegrityError (DB constraints)
    if isinstance(exc, IntegrityError):
        return _integrity_error_response(exc)

    # DRF exception_handler (ValidationError, AuthenticationFailed, etc.)
    response = exception_handler(exc, context)

    if response is not None:
        detail = getattr(exc, "detail", str(exc))
        message = _normalize_message(detail)
        code = getattr(exc, "code", None) or _infer_code(message)
        response.data = {"error": {"code": code, "message": message}}
        response["Content-Type"] = "application/json"
        return response

    # Unhandled exception: return consistent format (500)
    return _error_response(
        "INTERNAL_ERROR",
        "Erro interno do servidor",
        status=500,
    )


def _integrity_error_response(exc):
    """Handle IntegrityError: no_overlap -> CONFLICT_SCHEDULE 409, else CPF_DUPLICATE 400."""
    err_str = str(exc).lower()
    if "no_overlap" in err_str or "exclusion" in err_str:
        return _error_response("CONFLICT_SCHEDULE", "Conflito de horário", status=409)
    return _error_response(
        "CPF_DUPLICATE",
        "CPF já cadastrado neste tenant",
        status=400,
    )
