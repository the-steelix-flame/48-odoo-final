"""Subscription plan administration.  Owner: the-steelix-flame.

A plan is the *billing policy* a subscription runs under: how often it renews,
what a mid-cycle change costs, and what cancelling does to the customer's
money. `subscriptions/services.py` reads those four answers off the plan and
never asks the operator again — which is exactly why defining one is an admin
act and not a per-order choice.

NOTE FOR @anubhaw0raj: `RecurringPlan` is your model and nothing here touches
it structurally — no migration, no new fields, no change to how `services.py`
reads a plan. This is a NEW file in `accounts` (same reasoning as
`businesses.py`) so the admin surface stays in one lane and never conflicts
with `subscriptions/`.

The one rule with teeth is `interval`. `Subscription.current_period_start` and
`_end` were computed from it at activation and `renew()` keeps rolling them
forward by it, so re-timing a plan that already has live subscriptions would
leave those windows describing a cadence the plan no longer claims. Refused.
The other three policies are read at the moment an event happens, so editing
them only ever affects future events — allowed.
"""

from __future__ import annotations

import re
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, QuerySet

from apps.accounts.models import User
from apps.common.enums import (
    CancellationPolicy,
    ProrationMode,
    RecurringInterval,
    RefundMode,
    SubscriptionStatus,
)
from apps.common.errors import NotFound, ValidationError
from apps.catalog.models import Product, ProductCategory
from apps.subscriptions.models import RecurringPlan

#: Matches `RecurringPlan.name`'s column width. Checked here so the admin gets
#: a sentence back instead of a database error.
NAME_MAX_LENGTH = 120

#: The four policy fields, each with the enum that bounds it.
POLICY_FIELDS = {
    "interval": RecurringInterval,
    "proration_mode": ProrationMode,
    "cancellation_policy": CancellationPolicy,
    "refund_mode": RefundMode,
}

EDITABLE_FIELDS = ("name", *POLICY_FIELDS, "bill_in_advance", "is_active")


# ---------------------------------------------------------------- reading
def queryset() -> QuerySet[RecurringPlan]:
    """Every plan, retired ones included, with the usage counts the screen shows.

    Deliberately unfiltered: `GET /subscriptions/plans` shows only what a rep
    may still pick, but an admin managing plans has to see the retired ones or
    they cannot bring one back.
    """
    return RecurringPlan.objects.annotate(
        subscription_count=Count("subscriptions", distinct=True),
        active_subscription_count=Count(
            "subscriptions",
            filter=Q(subscriptions__status=SubscriptionStatus.ACTIVE),
            distinct=True,
        ),
        # Cancelled subscriptions keep pointing at the plan for their history,
        # but they are not billing any more and must not freeze the interval.
        live_subscription_count=Count(
            "subscriptions",
            filter=~Q(subscriptions__status=SubscriptionStatus.CANCELLED),
            distinct=True,
        ),
        product_count=Count("products", distinct=True),
    ).order_by("-is_active", "name")


def get_plan(plan_id: int) -> RecurringPlan:
    try:
        return queryset().get(pk=plan_id)
    except RecurringPlan.DoesNotExist:
        raise NotFound("Plan not found")


def live_subscription_count(plan: RecurringPlan) -> int:
    """Subscriptions still billing on this plan. Paused counts — it resumes.

    Prefers the annotation so listing N plans stays one query, and falls back
    to a count for a plain instance handed in from elsewhere.
    """
    annotated = getattr(plan, "live_subscription_count", None)
    if annotated is not None:
        return annotated
    return plan.subscriptions.exclude(status=SubscriptionStatus.CANCELLED).count()


# ---------------------------------------------------------------- validation
def _clean_name(name: str, *, exclude_pk: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("A plan name is required")
    if len(name) > NAME_MAX_LENGTH:
        raise ValidationError(f"Plan names are limited to {NAME_MAX_LENGTH} characters")

    # `unique=True` on the column is case-SENSITIVE, so "Monthly" and "monthly"
    # would both be accepted and then sit side by side in every plan picker.
    clash = RecurringPlan.objects.filter(name__iexact=name)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise ValidationError(f"A plan named '{name}' already exists")
    return name


def _clean_policy(field: str, value: str) -> str:
    allowed = [choice.value for choice in POLICY_FIELDS[field]]
    if value not in allowed:
        raise ValidationError(
            f"{field.replace('_', ' ').capitalize()} must be one of {', '.join(allowed)}",
            field=field,
        )
    return value


# ---------------------------------------------------------------- writing
@transaction.atomic
def create_plan(
    *,
    name: str,
    interval: str = RecurringInterval.MONTHLY,
    proration_mode: str = ProrationMode.DAILY,
    cancellation_policy: str = CancellationPolicy.IMMEDIATE,
    refund_mode: str = RefundMode.PRORATED,
    bill_in_advance: bool = True,
    is_active: bool = True,
    list_price: Decimal | None = None,
    cost_price: Decimal | None = None,
    actor: User | None = None,
) -> RecurringPlan:
    """Define a new billing policy, and the product that sells it.

    A plan on its own cannot be sold. `QuotationLine.product` is a required
    foreign key, so a policy with no product behind it can never go on a
    quotation, never be suggested in the upsell panel, and never become a
    subscription — it just sits in the list looking available. Creating the
    companion product here is what makes "add a plan" mean "add something a rep
    can actually sell".

    Pass `list_price=None` to skip it, for the rare case where an existing
    product is going to be repointed at this plan instead.
    """
    plan = RecurringPlan.objects.create(
        name=_clean_name(name),
        interval=_clean_policy("interval", interval),
        proration_mode=_clean_policy("proration_mode", proration_mode),
        cancellation_policy=_clean_policy("cancellation_policy", cancellation_policy),
        refund_mode=_clean_policy("refund_mode", refund_mode),
        bill_in_advance=bill_in_advance,
        is_active=is_active,
    )
    if list_price is not None:
        create_companion_product(plan, list_price=list_price, cost_price=cost_price)
    return get_plan(plan.pk)


#: Where a plan's own product lands. Subscriptions are their own category so
#: the discount ceiling on hardware never silently governs a billing policy.
SUBSCRIPTION_CATEGORY_CODE = "SUBSCRIPTION"


def _subscription_category() -> ProductCategory:
    category = ProductCategory.objects.filter(code=SUBSCRIPTION_CATEGORY_CODE).first()
    if category is None:
        raise ValidationError(
            "There is no Subscription product category to file this plan under. "
            "Run `manage.py seed_demo`, or create the category first."
        )
    return category


def _unique_sku(plan: RecurringPlan) -> str:
    """SB-<slug of the plan name>, with a numeric suffix only if it collides."""
    base = re.sub(r"[^A-Z0-9]+", "-", plan.name.upper()).strip("-")[:40] or "PLAN"
    candidate = f"SB-{base}"
    suffix = 2
    while Product.objects.filter(sku=candidate).exists():
        candidate = f"SB-{base}-{suffix}"
        suffix += 1
    return candidate


@transaction.atomic
def create_companion_product(
    plan: RecurringPlan, *, list_price: Decimal, cost_price: Decimal | None = None
) -> Product:
    """The sellable half of a plan."""
    if list_price is None or Decimal(list_price) <= 0:
        raise ValidationError("A plan's product needs a list price above zero")
    cost = Decimal(cost_price) if cost_price is not None else Decimal(list_price) * Decimal("0.4")
    if cost >= Decimal(list_price):
        raise ValidationError(
            "Cost price must be below the list price, or every quote carrying "
            "this plan books a loss."
        )
    return Product.objects.create(
        name=plan.name,
        sku=_unique_sku(plan),
        category=_subscription_category(),
        base_price=Decimal(list_price),
        cost_price=cost,
        tax_percent=Decimal("0"),
        unit="Recurring",
        is_subscription=True,
        recurring_plan=plan,
        is_active=plan.is_active,
    )


@transaction.atomic
def update_plan(plan: RecurringPlan, *, actor: User | None = None, **changes) -> RecurringPlan:
    """Edit a plan in place. `None` values mean "leave this field alone"."""
    changes = {field: value for field, value in changes.items() if value is not None}
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError(f"Cannot edit {', '.join(sorted(unknown))} on a plan")

    new_interval = changes.get("interval")
    if new_interval and new_interval != plan.interval:
        live = live_subscription_count(plan)
        if live:
            raise ValidationError(
                f"'{plan.name}' has {live} subscription(s) whose billing periods were "
                f"built from its {plan.interval.lower()} interval. Retire this plan and "
                "create the new cadence alongside it rather than re-timing orders "
                "already in flight.",
                live_subscriptions=live,
            )

    if "name" in changes:
        plan.name = _clean_name(changes["name"], exclude_pk=plan.pk)
    for field in POLICY_FIELDS:
        if field in changes:
            setattr(plan, field, _clean_policy(field, changes[field]))
    for field in ("bill_in_advance", "is_active"):
        if field in changes:
            setattr(plan, field, bool(changes[field]))

    plan.save()
    return get_plan(plan.pk)


def set_active(plan: RecurringPlan, *, enabled: bool, actor: User | None = None) -> RecurringPlan:
    """Retire a plan, or bring it back.

    Retiring is deliberately not deletion. `Subscription.plan` is PROTECTed and
    the whole proration history hangs off it, so deleting a plan that ever sold
    would take the audit trail with it. Clearing `is_active` removes it from the
    pickers — `GET /subscriptions/plans` filters on exactly this flag — while
    every subscription already on it keeps billing to the same rules.
    """
    plan.is_active = enabled
    plan.save(update_fields=["is_active", "updated_at"])
    return get_plan(plan.pk)


# ---------------------------------------------------------------- explaining
def policy_summary(plan: RecurringPlan) -> list[str]:
    """Plain-English reading of the four policy fields.

    Written for the admin about to save one: "DAILY / END_OF_PERIOD / PRORATED"
    read together is not obvious even to the person who just picked them, and
    the choice is hard to walk back once orders are on it.
    """
    interval = dict(RecurringInterval.choices)[plan.interval].lower()
    billing = (
        "invoiced at the start of each period"
        if plan.bill_in_advance
        else "invoiced at the end of each period"
    )
    lines = [f"Renews {interval}, {billing}."]

    if plan.proration_mode == ProrationMode.DAILY:
        lines.append(
            "A mid-cycle quantity change is charged or credited for the unused days only."
        )
    elif plan.proration_mode == ProrationMode.NONE:
        lines.append(
            "A mid-cycle quantity change costs nothing now — the new quantity starts "
            "billing from the next period."
        )
    else:
        lines.append(
            "A mid-cycle quantity change is charged or credited a whole period, no matter "
            "which day it happens on."
        )

    if plan.cancellation_policy == CancellationPolicy.END_OF_PERIOD:
        lines.append(
            "Cancelling lets it run to the end of the paid period, so nothing is refunded."
        )
    elif plan.refund_mode == RefundMode.PRORATED:
        lines.append(
            "Cancelling stops it immediately and credits the unused remainder of the period."
        )
    else:
        lines.append("Cancelling stops it immediately, with no refund for the unused days.")
    return lines


def policy_warnings(plan: RecurringPlan) -> list[str]:
    """Combinations that are legal but mean less than the admin thinks.

    Not errors — an admin is allowed to configure a plan this way. Saying so at
    the point of choosing beats discovering it from a customer's refund.
    """
    warnings: list[str] = []
    if (
        plan.cancellation_policy == CancellationPolicy.END_OF_PERIOD
        and plan.refund_mode == RefundMode.PRORATED
    ):
        # `services.cancel` returns before it ever consults `refund_mode` on
        # this branch, so the setting is inert rather than wrong.
        warnings.append(
            "Refund mode is set to prorated, but end-of-period cancellation never "
            "reaches it — no credit note will ever be issued on this plan."
        )
    if plan.proration_mode == ProrationMode.FULL_PERIOD:
        warnings.append(
            "Full-period proration bills an upgrade made on the last day of a period "
            "as if it had run the whole period."
        )
    return warnings
