"""
OpenAPI schema definitions for standardized error responses.
Format: {"error": {"code": "...", "message": "..."}}
"""
from drf_spectacular.utils import OpenApiExample, OpenApiResponse

# Reusable error response definitions for drf-spectacular
# Used in extend_schema(responses=...) to document error format in Swagger

ERROR_400 = OpenApiResponse(
    description="Erro de validação ou requisição inválida",
    examples=[
        OpenApiExample(
            "invalid_cpf",
            value={"error": {"code": "INVALID_CPF", "message": "CPF inválido."}},
            response_only=True,
            status_codes=["400"],
        ),
        OpenApiExample(
            "validation_error",
            value={"error": {"code": "VALIDATION_ERROR", "message": "Campo obrigatório."}},
            response_only=True,
            status_codes=["400"],
        ),
    ],
)

ERROR_404 = OpenApiResponse(
    description="Recurso não encontrado",
    examples=[
        OpenApiExample(
            "not_found",
            value={"error": {"code": "NOT_FOUND", "message": "Recurso não encontrado"}},
            response_only=True,
            status_codes=["404"],
        ),
    ],
)

ERROR_409 = OpenApiResponse(
    description="Conflito (ex: horário já ocupado)",
    examples=[
        OpenApiExample(
            "conflict_schedule",
            value={"error": {"code": "CONFLICT_SCHEDULE", "message": "Conflito de horário"}},
            response_only=True,
            status_codes=["409"],
        ),
    ],
)

ERROR_422 = OpenApiResponse(
    description="Transição de estado inválida",
    examples=[
        OpenApiExample(
            "invalid_transition",
            value={
                "error": {
                    "code": "INVALID_TRANSITION",
                    "message": "Cannot transition from 'CONFIRMED' to 'PRE_BOOKED'. Allowed transitions: ['COMPLETED', 'NO_SHOW', 'CANCELLED']",
                }
            },
            response_only=True,
            status_codes=["422"],
        ),
    ],
)

# Dict for easy inclusion in extend_schema(responses={...})
ERROR_RESPONSES = {
    400: ERROR_400,
    404: ERROR_404,
    409: ERROR_409,
    422: ERROR_422,
}
