"""Domain exceptions and their HTTP mapping.

Services raise these; routers never catch them. The handlers below turn each
into the shape documented in WORKFLOW.md §11, so the frontend can rely on one
error contract across all ten routers.
"""

from ninja import NinjaAPI


class DomainError(Exception):
    """Base for anything the business rules refuse to do."""

    status = 422

    def __init__(self, detail: str, **context):
        super().__init__(detail)
        self.detail = detail
        self.context = context


class ValidationError(DomainError):
    status = 400


class PermissionDenied(DomainError):
    status = 403


class NotFound(DomainError):
    """Also used for 'exists but not yours' — we don't leak existence."""

    status = 404

    def __init__(self, detail: str = "Not found", **context):
        super().__init__(detail, **context)


class InvalidTransition(DomainError):
    """Illegal state-machine move. The UI should refresh, not retry."""

    status = 409


class InsufficientStock(DomainError):
    status = 422


def register_exception_handlers(api: NinjaAPI) -> None:
    @api.exception_handler(DomainError)
    def _handle_domain_error(request, exc: DomainError):
        body = {"detail": exc.detail}
        if exc.context:
            body["context"] = exc.context
        return api.create_response(request, body, status=exc.status)
