"""Admin back-end: business management.  Owner: the-steelix-flame.

Mounted at /api/admin/. Every route here is ADMIN-only (`require_role` treats
ADMIN as implicitly allowed everywhere, so naming it explicitly is what makes
this an admin-only surface rather than a general internal one).

NEW FILE — see the note at the top of `businesses.py` about why this doesn't
live in `accounts/api.py`.
"""

from datetime import datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts import analytics, businesses, plans, staff
from apps.accounts.auth import internal_auth, require_role
from apps.accounts.models import Customer, SalesTeam, User
from apps.common.enums import Role
from apps.common.errors import NotFound

router = Router(auth=internal_auth)


# ---------------------------------------------------------------- schemas
class BusinessOut(Schema):
    """One row of the Business Management table."""

    id: int
    name: str
    tier: str
    currency: str
    contact_email: str
    owner_rep_id: int | None = None
    owner_rep_name: str | None = None
    default_price_list_id: int | None = None

    # Portal login state. `has_portal_login` and `portal_access_enabled` are
    # different questions: a business can have a login that is suspended.
    has_portal_login: bool
    portal_login_email: str | None = None
    portal_access_enabled: bool
    portal_last_login: datetime | None = None
    portal_created_at: datetime | None = None

    quotation_count: int = 0

    @staticmethod
    def resolve_owner_rep_name(obj) -> str | None:
        if isinstance(obj, dict):
            return obj.get("owner_rep_name")
        return (obj.owner_rep.full_name or obj.owner_rep.email) if obj.owner_rep_id else None

    @staticmethod
    def resolve_has_portal_login(obj) -> bool:
        if isinstance(obj, dict):
            return obj["has_portal_login"]
        return obj.portal_user_id is not None

    @staticmethod
    def resolve_portal_login_email(obj) -> str | None:
        if isinstance(obj, dict):
            return obj.get("portal_login_email")
        return obj.portal_user.email if obj.portal_user_id else None

    @staticmethod
    def resolve_portal_access_enabled(obj) -> bool:
        if isinstance(obj, dict):
            return obj["portal_access_enabled"]
        return bool(obj.portal_user_id and obj.portal_user.is_active)

    @staticmethod
    def resolve_portal_last_login(obj):
        if isinstance(obj, dict):
            return obj.get("portal_last_login")
        return obj.portal_user.last_login if obj.portal_user_id else None

    @staticmethod
    def resolve_portal_created_at(obj):
        if isinstance(obj, dict):
            return obj.get("portal_created_at")
        return obj.portal_user.date_joined if obj.portal_user_id else None

    @staticmethod
    def resolve_quotation_count(obj) -> int:
        if isinstance(obj, dict):
            return obj.get("quotation_count", 0)
        return obj.quotations.count()


class CredentialsOut(Schema):
    """The only time a password is ever returned. Not stored, not recoverable."""

    business: BusinessOut
    portal_login_email: str
    password: str
    notice: str = (
        "Share these credentials with the business now — this password cannot be "
        "shown again. If it is lost, reset it to issue a new one."
    )


class CreateBusinessIn(Schema):
    name: str
    contact_email: str = ""
    tier: str = "BRONZE"
    currency: str = "USD"
    owner_rep_id: int | None = None
    default_price_list_id: int | None = None
    create_portal_login: bool = True


class UpdateBusinessIn(Schema):
    name: str | None = None
    tier: str | None = None
    currency: str | None = None
    contact_email: str | None = None
    owner_rep_id: int | None = None
    default_price_list_id: int | None = None


class AccessIn(Schema):
    enabled: bool


# ---------------------------------------------------------------- helpers
def _queryset():
    return Customer.objects.select_related("owner_rep", "portal_user")


def _get(business_id: int) -> Customer:
    try:
        return _queryset().get(pk=business_id)
    except Customer.DoesNotExist:
        raise NotFound("Business not found")


def _credentials_payload(result: businesses.OnboardingResult) -> dict:
    return {
        "business": result.customer,
        "portal_login_email": result.portal_user.email if result.portal_user else "",
        "password": result.password or "",
    }


# ---------------------------------------------------------------- routes
@router.get("/businesses", response=list[BusinessOut])
def list_businesses(request, q: str | None = None):
    require_role(request, Role.ADMIN)
    qs = _queryset()
    if q:
        qs = qs.filter(name__icontains=q)
    return list(qs.order_by("name"))


@router.post("/businesses", response=CredentialsOut)
def create_business(request, payload: CreateBusinessIn):
    """Register a business and mint its portal login.

    Returns the generated password once. Nothing else in the system can read it
    back afterwards.
    """
    require_role(request, Role.ADMIN)
    result = businesses.create_business(actor=request.auth, **payload.dict())
    return _credentials_payload(result)


@router.get("/businesses/{business_id}", response=BusinessOut)
def get_business(request, business_id: int):
    require_role(request, Role.ADMIN)
    return _get(business_id)


@router.patch("/businesses/{business_id}", response=BusinessOut)
def update_business(request, business_id: int, payload: UpdateBusinessIn):
    require_role(request, Role.ADMIN)
    business = _get(business_id)
    for field, value in payload.dict(exclude_unset=True).items():
        if value is not None:
            setattr(business, field, value)
    business.save()
    business.refresh_from_db()
    return business


@router.post("/businesses/{business_id}/portal-login", response=CredentialsOut)
def issue_login(request, business_id: int):
    """Give a portal login to a business registered without one."""
    require_role(request, Role.ADMIN)
    result = businesses.issue_portal_login(_get(business_id), actor=request.auth)
    return _credentials_payload(result)


@router.post("/businesses/{business_id}/reset-password", response=CredentialsOut)
def reset_password(request, business_id: int):
    """Issue a new password. The previous one stops working immediately."""
    require_role(request, Role.ADMIN)
    result = businesses.reset_portal_password(_get(business_id), actor=request.auth)
    return _credentials_payload(result)


@router.post("/businesses/{business_id}/access", response=BusinessOut)
def set_access(request, business_id: int, payload: AccessIn):
    """Suspend or restore portal access without deleting negotiation history."""
    require_role(request, Role.ADMIN)
    business = businesses.set_portal_access(
        _get(business_id), enabled=payload.enabled, actor=request.auth
    )
    business.refresh_from_db()
    return business


# ================================================================= users
# Admin provisions staff accounts and hands the credentials over. Customer
# logins are NOT created here — see the note in `staff.py`.


class AdminUserOut(Schema):
    id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    sales_team_id: int | None = None
    sales_team_name: str | None = None
    date_joined: datetime | None = None
    last_login: datetime | None = None

    #: A cheap at-a-glance activity figure for the list view. The full picture
    #: lives on the detail page.
    quotations_owned: int = 0
    approvals_made: int = 0
    business_name: str | None = None

    @staticmethod
    def resolve_sales_team_name(obj) -> str | None:
        return obj.sales_team.name if obj.sales_team_id else None

    @staticmethod
    def resolve_quotations_owned(obj) -> int:
        return obj.quotations.count()

    @staticmethod
    def resolve_approvals_made(obj) -> int:
        return obj.approval_steps.exclude(acted_at=None).count()

    @staticmethod
    def resolve_business_name(obj) -> str | None:
        profile = getattr(obj, "customer_profile", None)
        return profile.name if profile else None


class UserCredentialsOut(Schema):
    """Returned only by create and reset. Never recoverable afterwards."""

    user: AdminUserOut
    email: str
    password: str
    notice: str = (
        "Share these credentials with the user now — this password cannot be shown "
        "again. If it is lost, reset it to issue a new one."
    )


class MetricOut(Schema):
    label: str
    value: str
    hint: str | None = None


class SectionOut(Schema):
    title: str
    metrics: list[MetricOut]


class QuotationRefOut(Schema):
    id: int
    number: str
    customer_name: str
    status: str
    risk_band: str
    total: str
    created_at: datetime


class DecisionRefOut(Schema):
    quotation_id: int
    quotation_number: str
    customer_name: str
    decision: str
    note: str
    acted_at: datetime | None = None


class UserDetailOut(Schema):
    user: AdminUserOut
    window_days: int
    sections: list[SectionOut]
    recent_quotations: list[QuotationRefOut]
    recent_decisions: list[DecisionRefOut]


class CreateUserIn(Schema):
    email: str
    full_name: str
    role: str
    sales_team_id: int | None = None


class RoleIn(Schema):
    role: str


class TeamOut(Schema):
    id: int
    name: str


def _user_queryset():
    return User.objects.select_related("sales_team", "customer_profile")


def _get_user(user_id: int) -> User:
    try:
        return _user_queryset().get(pk=user_id)
    except User.DoesNotExist:
        raise NotFound("User not found")


def _user_credentials(result: staff.AccountResult) -> dict:
    return {"user": result.user, "email": result.user.email, "password": result.password or ""}


@router.get("/users", response=list[AdminUserOut])
def list_users(request, role: str | None = None, q: str | None = None, include_inactive: bool = True):
    require_role(request, Role.ADMIN)
    qs = _user_queryset()
    if role:
        qs = qs.filter(role=role)
    if q:
        qs = qs.filter(email__icontains=q) | qs.filter(full_name__icontains=q)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return list(qs.order_by("role", "full_name"))


@router.post("/users", response=UserCredentialsOut)
def create_user(request, payload: CreateUserIn):
    """Create a staff account and mint its first password."""
    require_role(request, Role.ADMIN)
    result = staff.create_account(actor=request.auth, **payload.dict())
    return _user_credentials(result)


@router.get("/users/{user_id}", response=UserDetailOut)
def get_user(request, user_id: int):
    """Profile plus role-appropriate analytics."""
    require_role(request, Role.ADMIN)
    user = _get_user(user_id)
    data = analytics.user_analytics(user)
    return {
        "user": user,
        "window_days": data["window_days"],
        "sections": data["sections"],
        "recent_quotations": data["recent_quotations"],
        "recent_decisions": data["recent_decisions"],
    }


@router.post("/users/{user_id}/reset-password", response=UserCredentialsOut)
def reset_user_password(request, user_id: int):
    require_role(request, Role.ADMIN)
    return _user_credentials(staff.reset_password(_get_user(user_id), actor=request.auth))


@router.post("/users/{user_id}/access", response=AdminUserOut)
def set_user_access(request, user_id: int, payload: AccessIn):
    """Deactivate or restore. Never deletes — the audit trail points here."""
    require_role(request, Role.ADMIN)
    return staff.set_access(_get_user(user_id), enabled=payload.enabled, actor=request.auth)


@router.post("/users/{user_id}/role", response=AdminUserOut)
def change_user_role(request, user_id: int, payload: RoleIn):
    require_role(request, Role.ADMIN)
    return staff.change_role(_get_user(user_id), role=payload.role, actor=request.auth)


@router.get("/teams", response=list[TeamOut])
def list_teams(request):
    require_role(request, Role.ADMIN)
    return list(SalesTeam.objects.order_by("name"))


# ================================================================= plans
# Subscription plans are the billing policy every recurring order inherits.
# Defining one is an admin act — see `plans.py` for why, and for the single
# rule that refuses an edit rather than warning about it.


class PlanOut(Schema):
    id: int
    name: str
    interval: str
    proration_mode: str
    cancellation_policy: str
    refund_mode: str
    bill_in_advance: bool
    is_active: bool
    created_at: datetime

    #: Usage, so "retire this plan" is never a decision made blind.
    subscription_count: int = 0
    active_subscription_count: int = 0
    product_count: int = 0

    #: The screen disables the interval field on this rather than letting the
    #: admin pick a value the server is going to reject.
    interval_locked: bool = False
    policy_summary: list[str] = []
    policy_warnings: list[str] = []

    @staticmethod
    def resolve_interval_locked(obj) -> bool:
        return plans.live_subscription_count(obj) > 0

    @staticmethod
    def resolve_policy_summary(obj) -> list[str]:
        return plans.policy_summary(obj)

    @staticmethod
    def resolve_policy_warnings(obj) -> list[str]:
        return plans.policy_warnings(obj)


class CreatePlanIn(Schema):
    name: str
    interval: str = "MONTHLY"
    proration_mode: str = "DAILY"
    cancellation_policy: str = "IMMEDIATE"
    refund_mode: str = "PRORATED"
    bill_in_advance: bool = True
    is_active: bool = True

    #: The plan's own product is created from these. Without a price the plan
    #: has nothing sellable behind it, so it can never reach a quotation or the
    #: upsell panel. Null skips it, for repointing an existing product instead.
    list_price: Decimal | None = None
    cost_price: Decimal | None = None


class UpdatePlanIn(Schema):
    """Every field optional — `None` means "leave this one alone"."""

    name: str | None = None
    interval: str | None = None
    proration_mode: str | None = None
    cancellation_policy: str | None = None
    refund_mode: str | None = None
    bill_in_advance: bool | None = None
    is_active: bool | None = None


@router.get("/plans", response=list[PlanOut])
def list_plans(request, include_retired: bool = True):
    """Every plan. Unlike `/subscriptions/plans`, retired ones are included —
    an admin who cannot see a retired plan cannot bring it back."""
    require_role(request, Role.ADMIN)
    qs = plans.queryset()
    if not include_retired:
        qs = qs.filter(is_active=True)
    return list(qs)


@router.post("/plans", response=PlanOut)
def create_plan(request, payload: CreatePlanIn):
    """Define a new subscription plan. Live for reps as soon as it is active."""
    require_role(request, Role.ADMIN)
    return plans.create_plan(actor=request.auth, **payload.dict())


@router.get("/plans/{plan_id}", response=PlanOut)
def get_plan(request, plan_id: int):
    require_role(request, Role.ADMIN)
    return plans.get_plan(plan_id)


@router.patch("/plans/{plan_id}", response=PlanOut)
def update_plan(request, plan_id: int, payload: UpdatePlanIn):
    require_role(request, Role.ADMIN)
    return plans.update_plan(
        plans.get_plan(plan_id), actor=request.auth, **payload.dict(exclude_unset=True)
    )


@router.post("/plans/{plan_id}/active", response=PlanOut)
def set_plan_active(request, plan_id: int, payload: AccessIn):
    """Retire a plan or restore it. Never deletes — the billing history points here."""
    require_role(request, Role.ADMIN)
    return plans.set_active(plans.get_plan(plan_id), enabled=payload.enabled, actor=request.auth)
