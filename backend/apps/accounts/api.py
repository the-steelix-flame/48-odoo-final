"""Auth + customer directory.  Owner: sinjeki."""

from django.contrib.auth import authenticate
from ninja import Router

from apps.accounts.auth import any_auth, internal_auth, require_role
from apps.accounts.models import Customer, User
from apps.accounts.schemas import (
    AuthOut,
    CustomerIn,
    CustomerOut,
    LoginIn,
    SignupIn,
    UserOut,
)
from apps.accounts.tokens import mint_token, touch_last_login
from apps.common.enums import Role
from apps.common.errors import PermissionDenied, ValidationError

router = Router()


@router.post("/login", response=AuthOut, auth=None)
def login(request, payload: LoginIn):
    """Email + password against the real Django hasher.

    Simplified (our own signed token instead of Firebase), never faked.
    """
    user = authenticate(request, username=payload.email, password=payload.password)
    if user is None or not user.is_active:
        raise PermissionDenied("Invalid email or password")
    touch_last_login(user)
    return {"token": mint_token(user), "user": user}


@router.post("/signup", response=AuthOut, auth=None)
def signup(request, payload: SignupIn):
    if User.objects.filter(email__iexact=payload.email).exists():
        raise ValidationError("An account with that email already exists")
    if payload.role not in Role.values:
        raise ValidationError(f"Unknown role {payload.role}")
    user = User.objects.create_user(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
    )
    return {"token": mint_token(user), "user": user}


@router.get("/me", response=UserOut, auth=any_auth)
def me(request):
    return request.auth


@router.get("/users", response=list[UserOut], auth=internal_auth)
def list_users(request, role: str | None = None):
    """Used by the reporting filters and by approval-step assignment."""
    qs = User.objects.filter(is_active=True).select_related("sales_team")
    if role:
        qs = qs.filter(role=role)
    return list(qs.order_by("full_name"))


@router.get("/customers", response=list[CustomerOut], auth=internal_auth)
def list_customers(request):
    return list(Customer.objects.select_related("owner_rep").all())


@router.post("/customers", response=CustomerOut, auth=internal_auth)
def create_customer(request, payload: CustomerIn):
    require_role(request, Role.ADMIN, Role.SALES_MANAGER, Role.SALES_REP)
    return Customer.objects.create(**payload.dict())
