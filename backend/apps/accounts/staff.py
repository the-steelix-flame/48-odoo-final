"""Internal user provisioning.  Owner: the-steelix-flame.

The admin creates staff accounts and hands the credentials to the person. Same
posture as `businesses.py`: the generated password is returned exactly once and
stored only as a hash.

Customer logins are deliberately NOT creatable here — they're created by
`businesses.create_business`, which also makes the `Customer` row that the
portal's token check depends on. A `CUSTOMER` user without a `Customer` record
can log in and then hit a wall on every portal route, so this module refuses to
make one and points at the right door instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.accounts.businesses import generate_password
from apps.accounts.models import SalesTeam, User
from apps.common.enums import INTERNAL_ROLES, Role
from apps.common.errors import ValidationError


@dataclass
class AccountResult:
    """`password` is populated only on the call that created or reset it."""

    user: User
    password: str | None


def _assert_internal_role(role: str) -> None:
    if role == Role.CUSTOMER:
        raise ValidationError(
            "Customer logins are created through Business Management, which also "
            "creates the business record the portal needs. Add the business there instead."
        )
    if role not in [r.value for r in INTERNAL_ROLES]:
        raise ValidationError(f"Unknown role {role}")


@transaction.atomic
def create_account(
    *,
    email: str,
    full_name: str,
    role: str,
    sales_team_id: int | None = None,
    actor: User | None = None,
) -> AccountResult:
    """Create an internal user and mint their first password."""
    email = (email or "").strip().lower()
    full_name = (full_name or "").strip()

    if not email:
        raise ValidationError("An email address is required")
    if not full_name:
        raise ValidationError("A full name is required")
    _assert_internal_role(role)

    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError(f"{email} already has an account")
    if sales_team_id and not SalesTeam.objects.filter(pk=sales_team_id).exists():
        raise ValidationError("That sales team does not exist")

    password = generate_password()
    user = User.objects.create_user(
        email=email,
        password=password,
        full_name=full_name,
        role=role,
        sales_team_id=sales_team_id,
        # Admins need the Django admin too; everyone else works in the app.
        is_staff=role == Role.ADMIN,
        is_superuser=role == Role.ADMIN,
    )
    return AccountResult(user=user, password=password)


@transaction.atomic
def reset_password(user: User, *, actor: User | None = None) -> AccountResult:
    """Mint a fresh password and re-enable the account.

    Reset is how a locked-out person gets back in, so leaving them disabled
    would make it a trap.
    """
    password = generate_password()
    user.set_password(password)
    user.is_active = True
    user.save(update_fields=["password", "is_active"])
    return AccountResult(user=user, password=password)


@transaction.atomic
def set_access(user: User, *, enabled: bool, actor: User | None = None) -> User:
    """Deactivate or restore an account.

    Never deletes: quotations, approval decisions and audit events all point at
    this row, and `on_delete=SET_NULL` on the audit trail would quietly turn a
    named decision into an anonymous one.
    """
    if actor is not None and actor.pk == user.pk and not enabled:
        raise ValidationError("You cannot deactivate your own account")
    if not enabled and user.role == Role.ADMIN and _last_active_admin(user):
        raise ValidationError(
            "This is the last active admin. Promote another admin before deactivating this one."
        )
    user.is_active = enabled
    user.save(update_fields=["is_active"])
    return user


@transaction.atomic
def change_role(user: User, *, role: str, actor: User | None = None) -> User:
    _assert_internal_role(role)
    if user.role == Role.ADMIN and role != Role.ADMIN and _last_active_admin(user):
        raise ValidationError(
            "This is the last active admin. Promote another admin before changing this role."
        )
    user.role = role
    user.is_staff = role == Role.ADMIN
    user.is_superuser = role == Role.ADMIN
    user.save(update_fields=["role", "is_staff", "is_superuser"])
    return user


def _last_active_admin(user: User) -> bool:
    """Guard against locking every human out of the back-end."""
    return not (
        User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=user.pk).exists()
    )
