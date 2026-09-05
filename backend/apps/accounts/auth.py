"""Ninja auth dependencies.

Usage in a router:

    from apps.accounts.auth import internal_auth, require_role
    from apps.common.enums import Role

    @router.get("/", auth=internal_auth)
    def list_things(request):
        ...

    @router.post("/{id}/approve", auth=internal_auth)
    def approve(request, id: int):
        require_role(request, Role.SALES_MANAGER, Role.ADMIN)
        ...

`request.auth` is the User. `require_role` raises 403 with a readable message.
"""

from __future__ import annotations

from ninja.security import HttpBearer

from apps.accounts.models import User
from apps.accounts.tokens import resolve_token
from apps.common.enums import INTERNAL_ROLES, Role
from apps.common.errors import PermissionDenied


class BearerAuth(HttpBearer):
    """Any authenticated user, internal or customer."""

    def authenticate(self, request, token: str) -> User | None:
        try:
            user = resolve_token(token)
        except PermissionDenied:
            return None
        request.user = user
        return user


class InternalAuth(BearerAuth):
    """Staff only. Customers get 401 on every internal router."""

    def authenticate(self, request, token: str) -> User | None:
        user = super().authenticate(request, token)
        if user is None or user.role not in INTERNAL_ROLES:
            return None
        return user


any_auth = BearerAuth()
internal_auth = InternalAuth()


def require_role(request, *roles: Role) -> User:
    """Assert the caller holds one of `roles`. Returns the user for convenience."""
    user: User = request.auth
    if user is None:
        raise PermissionDenied("Not authenticated")
    if Role.ADMIN not in roles:
        roles = (*roles, Role.ADMIN)  # Admin can do anything, always.
    if user.role not in roles:
        allowed = " or ".join(str(r) for r in roles)
        raise PermissionDenied(f"Requires role {allowed}")
    return user
