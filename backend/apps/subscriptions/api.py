"""Subscriptions & billing detail (screens 9, 10).  Owner: anubhaw0raj."""

from datetime import date, datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth, require_role
from apps.common.enums import Role, SubscriptionStatus
from apps.common.errors import NotFound
from apps.subscriptions import services
from apps.subscriptions.models import RecurringPlan, Subscription

router = Router(auth=internal_auth)


class PlanOut(Schema):
    id: int
    name: str
    interval: str
    proration_mode: str
    cancellation_policy: str
    refund_mode: str
    bill_in_advance: bool
    is_active: bool


class SubscriptionRowOut(Schema):
    """One row of screen 9."""

    id: int
    customer_id: int
    customer_name: str
    plan_id: int
    plan_name: str
    interval: str
    status: str
    quantity: Decimal
    unit_price: Decimal
    period_amount: Decimal
    next_bill_date: date | None = None

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.customer.name

    @staticmethod
    def resolve_plan_name(obj) -> str:
        return obj.plan.name

    @staticmethod
    def resolve_interval(obj) -> str:
        return obj.plan.interval


class SubscriptionEventOut(Schema):
    id: int
    event_type: str
    effective_date: date
    old_quantity: Decimal | None = None
    new_quantity: Decimal | None = None
    proration_amount: Decimal
    invoice_id: int | None = None
    credit_note_id: int | None = None
    note: str
    created_at: datetime


class OneTimeLineOut(Schema):
    description: str
    quantity: Decimal
    line_total: Decimal


class UpcomingBillOut(Schema):
    period_start: date
    period_end: date
    amount: Decimal


class BillingDetailOut(SubscriptionRowOut):
    """Screen 10: one-time lines and recurring lines, side by side.

    The two sections come from genuinely different tables — that's what makes
    this hybrid billing rather than a filtered list.
    """

    quotation_id: int | None = None
    quotation_number: str | None = None
    current_period_start: date
    current_period_end: date
    one_time_lines: list[OneTimeLineOut]
    upcoming_bills: list[UpcomingBillOut]
    events: list[SubscriptionEventOut]


class QuantityChangeIn(Schema):
    quantity: Decimal
    effective_date: date | None = None


class CancelIn(Schema):
    effective_date: date | None = None


def _get(subscription_id: int) -> Subscription:
    try:
        return Subscription.objects.select_related(
            "customer", "plan", "product", "quotation"
        ).get(pk=subscription_id)
    except Subscription.DoesNotExist:
        raise NotFound("Subscription not found")


@router.get("/plans", response=list[PlanOut])
def list_plans(request):
    return list(RecurringPlan.objects.filter(is_active=True))


@router.get("/", response=list[SubscriptionRowOut])
def list_subscriptions(request, status: str | None = None, customer_id: int | None = None):
    qs = Subscription.objects.select_related("customer", "plan")
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    return list(qs)


@router.get("/counts")
def subscription_counts(request):
    """The three chips at the top of screen 9."""
    qs = Subscription.objects.all()
    return {
        "active": qs.filter(status=SubscriptionStatus.ACTIVE).count(),
        "paused": qs.filter(status=SubscriptionStatus.PAUSED).count(),
        "cancelled": qs.filter(status=SubscriptionStatus.CANCELLED).count(),
    }


@router.get("/{subscription_id}", response=BillingDetailOut)
def get_subscription(request, subscription_id: int):
    from apps.common.enums import LineType
    from apps.subscriptions.proration import next_period

    subscription = _get(subscription_id)
    quotation = subscription.quotation

    # Next three billing periods, so the schedule is visible not implied.
    upcoming, cursor = [], subscription.current_period_end
    if subscription.status == SubscriptionStatus.ACTIVE:
        for _ in range(3):
            period = next_period(cursor, subscription.plan.interval)
            upcoming.append(
                {
                    "period_start": period.start,
                    "period_end": period.end,
                    "amount": subscription.period_amount,
                }
            )
            cursor = period.end

    data = {f: getattr(subscription, f) for f in (
        "id", "customer_id", "plan_id", "status", "quantity", "unit_price",
        "next_bill_date", "quotation_id", "current_period_start", "current_period_end",
    )}
    data.update(
        customer_name=subscription.customer.name,
        plan_name=subscription.plan.name,
        interval=subscription.plan.interval,
        period_amount=subscription.period_amount,
        quotation_number=quotation.number if quotation else None,
        one_time_lines=list(quotation.lines.filter(line_type=LineType.ONE_TIME))
        if quotation
        else [],
        upcoming_bills=upcoming,
        events=list(subscription.events.all()),
    )
    return data


@router.post("/{subscription_id}/quantity", response=BillingDetailOut)
def change_quantity(request, subscription_id: int, payload: QuantityChangeIn):
    """Modify Subscription — triggers proration automatically."""
    require_role(request, Role.FINANCE, Role.SALES_MANAGER, Role.SALES_REP)
    services.change_quantity(
        _get(subscription_id),
        payload.quantity,
        effective_date=payload.effective_date,
        actor=request.auth,
    )
    return get_subscription(request, subscription_id)


@router.post("/{subscription_id}/cancel", response=BillingDetailOut)
def cancel_subscription(request, subscription_id: int, payload: CancelIn):
    """Cancel Subscription — issues a partial refund credit note when due."""
    require_role(request, Role.FINANCE, Role.SALES_MANAGER)
    services.cancel(
        _get(subscription_id), effective_date=payload.effective_date, actor=request.auth
    )
    return get_subscription(request, subscription_id)
