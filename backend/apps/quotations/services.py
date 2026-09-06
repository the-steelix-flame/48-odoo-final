"""Quotation business logic.  Owner: the-steelix-flame.

Every write to a quotation goes through this module. Routers call these
functions; they never touch models directly. That is what guarantees the three
things the demo depends on:

  1. totals, margin, ceilings and risk are recomputed together, always
  2. every human action leaves an audit event
  3. `last_activity_at` is accurate, so the stalled-deal detector isn't lying
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product, ProductVariant
from apps.catalog.pricing import resolve_unit_price
from apps.common.enums import LineType, QuotationEventType, QuotationStatus
from apps.common.errors import InvalidTransition, NotFound, ValidationError
from apps.governance.models import (
    ApprovalRule,
    CategoryDiscountCeiling,
    RiskConfig,
    TierDiscountCeiling,
)
from apps.governance.risk import LineInput, RiskConfigData, score_quotation
from apps.quotations.models import Quotation, QuotationEvent, QuotationLine

ZERO = Decimal("0")
HUNDRED = Decimal("100")


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------
#: The complete set of legal moves. Anything not listed here raises.
#: One dict beats `if` statements scattered across six views.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    QuotationStatus.DRAFT: {
        QuotationStatus.PENDING_APPROVAL,
        QuotationStatus.APPROVED,
        QuotationStatus.CANCELLED,
    },
    QuotationStatus.PENDING_APPROVAL: {
        QuotationStatus.APPROVED,
        QuotationStatus.REJECTED,
        QuotationStatus.DRAFT,  # returned for revision
    },
    QuotationStatus.APPROVED: {
        QuotationStatus.SENT,
        QuotationStatus.CONFIRMED,
        # A customer can decline once it is in front of them. Reachable from
        # every state they can see, because "no thank you" is a legitimate
        # answer at any point in the conversation and the alternative is a
        # quote that sits open forever pretending to be live.
        QuotationStatus.REJECTED,
        QuotationStatus.CANCELLED,
    },
    QuotationStatus.SENT: {
        QuotationStatus.UNDER_NEGOTIATION,
        # A sent quote whose terms now breach a ceiling has to be able to go
        # back for approval. Without this the customer pressed Accept and got
        # "Cannot move a quotation from SENT to PENDING_APPROVAL" — the guard
        # firing correctly on a route that simply did not exist.
        QuotationStatus.PENDING_APPROVAL,
        QuotationStatus.CONFIRMED,
        QuotationStatus.REJECTED,
        QuotationStatus.CANCELLED,
    },
    QuotationStatus.UNDER_NEGOTIATION: {
        QuotationStatus.PENDING_APPROVAL,  # counter pushed it back over a ceiling
        QuotationStatus.APPROVED,
        QuotationStatus.CONFIRMED,
        QuotationStatus.REJECTED,
        QuotationStatus.CANCELLED,
    },
    QuotationStatus.CONFIRMED: set(),
    # Terminal. Matches WORKFLOW.md, which has always drawn REJECTED as an end
    # state; the DRAFT edge let a refused quote be quietly revived in place.
    QuotationStatus.REJECTED: set(),
    QuotationStatus.CANCELLED: set(),
}


def transition(quotation: Quotation, to_status: str, *, actor=None, note: str = "") -> Quotation:
    allowed = ALLOWED_TRANSITIONS.get(quotation.status, set())
    if to_status not in allowed:
        raise InvalidTransition(
            f"Cannot move a quotation from {quotation.status} to {to_status}",
            current_status=quotation.status,
            allowed=sorted(allowed),
        )
    quotation.status = to_status
    quotation.save(update_fields=["status", "updated_at"])
    return quotation


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
def record_event(
    quotation: Quotation,
    event_type: str,
    *,
    actor=None,
    note: str = "",
    **payload,
) -> QuotationEvent:
    """Write an audit row and refresh the activity clock, together."""
    quotation.last_activity_at = timezone.now()
    quotation.save(update_fields=["last_activity_at", "updated_at"])
    return QuotationEvent.objects.create(
        quotation=quotation,
        actor=actor,
        event_type=event_type,
        note=note,
        payload=payload,
    )


# --------------------------------------------------------------------------
# The recalculation pipeline
# --------------------------------------------------------------------------
def _ceiling_map() -> dict[int, Decimal]:
    return {
        c.category_id: Decimal(c.max_discount_percent)
        for c in CategoryDiscountCeiling.objects.all()
    }


def _tier_ceiling(tier: str) -> Decimal:
    row = TierDiscountCeiling.objects.filter(tier=tier).first()
    # No configured ceiling means "no discretion", not "unlimited". Failing
    # closed is the only safe default for a governance rule.
    return Decimal(row.max_discount_percent) if row else ZERO


@transaction.atomic
def terms_fingerprint(quotation: Quotation) -> str:
    """What an approver actually signs off, reduced to one comparable string.

    Every input that moves the money is in here and nothing else is. So a
    change to a price, a quantity, a line discount or the order discount stops
    matching by itself — there is no invalidation step to remember and
    therefore none to forget — while sending the quotation, which changes its
    status but not a single number, leaves the approval standing.

    Note it hashes INPUTS, not the computed totals: `recalculate` rewrites
    `line_total` constantly without anything having actually changed.
    """
    parts = [str(Decimal(quotation.order_discount_percent or 0))]
    for line in quotation.lines.order_by("id"):
        parts.append(
            f"{line.id}:{Decimal(line.quantity)}:{Decimal(line.unit_price)}:"
            f"{Decimal(line.discount_percent)}"
        )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def mark_terms_approved(quotation: Quotation) -> None:
    """Record that the CURRENT terms are the approved ones."""
    quotation.approved_terms_hash = terms_fingerprint(quotation)
    quotation.save(update_fields=["approved_terms_hash", "updated_at"])


def terms_are_approved(quotation: Quotation) -> bool:
    """True when nothing that affects the money has changed since sign-off."""
    return bool(quotation.approved_terms_hash) and (
        quotation.approved_terms_hash == terms_fingerprint(quotation)
    )


def order_discount_factor(quotation: Quotation) -> Decimal:
    """The multiplier from a line's own net to what is actually charged for it.

    `line_total` is net of that line's OWN discount but not of the order-level
    one — and the order-level one is exactly where a negotiated figure lands,
    because `accept_request` and `accept_counter` both write
    `order_discount_percent` rather than touching the lines. So anything that
    turns a quotation into money has to apply this, or it bills the price from
    before the negotiation.

    `recalculate` apportions the order discount by each line's share of the
    post-line-discount net, which reduces exactly to this single multiplier:

        order_discount_value × (line_total / net_after_lines)
          = net_after_lines × order% / 100 × line_total / net_after_lines
          = line_total × order% / 100

    so tax computed from this agrees with the tax on the quotation itself.
    """
    order_discount = Decimal(quotation.order_discount_percent or 0)
    return (HUNDRED - order_discount) / HUNDRED


def recalculate(quotation: Quotation) -> Quotation:
    """Recompute money, margin, per-line ceilings and the risk band.

    Called after every line mutation. Returns the same instance, saved.
    """
    lines = list(quotation.lines.select_related("product", "product__category"))
    ceilings = _ceiling_map()
    tier_ceiling = _tier_ceiling(quotation.customer.tier)
    order_discount = Decimal(quotation.order_discount_percent)

    subtotal = ZERO
    discount_total = ZERO
    tax_total = ZERO
    cost_total = ZERO
    risk_inputs: list[LineInput] = []

    for line in lines:
        qty = Decimal(line.quantity)
        price = Decimal(line.unit_price)
        line_subtotal = (qty * price).quantize(Decimal("0.01"))
        line_discount = (line_subtotal * Decimal(line.discount_percent) / HUNDRED).quantize(
            Decimal("0.01")
        )
        line_net = line_subtotal - line_discount

        category_ceiling = ceilings.get(line.product.category_id, tier_ceiling)
        allowed = min(tier_ceiling, category_ceiling)
        excess = max(ZERO, Decimal(line.discount_percent) - allowed)

        line.line_subtotal = line_subtotal
        line.line_total = line_net
        line.allowed_discount_percent = allowed
        line.discount_excess_points = excess
        line.margin_amount = line_net - (qty * Decimal(line.unit_cost))
        line.save(
            update_fields=[
                "line_subtotal",
                "line_total",
                "allowed_discount_percent",
                "discount_excess_points",
                "margin_amount",
                "updated_at",
            ]
        )

        subtotal += line_subtotal
        discount_total += line_discount
        cost_total += qty * Decimal(line.unit_cost)

        risk_inputs.append(
            LineInput(
                line_id=line.id,
                label=f"{line.description} ({line.product.category.name})",
                line_subtotal=line_subtotal,
                discount_percent=Decimal(line.discount_percent),
                category_ceiling=category_ceiling,
            )
        )

    # Order-level discount applies to what's left after line discounts.
    net_after_lines = subtotal - discount_total
    order_discount_value = (net_after_lines * order_discount / HUNDRED).quantize(Decimal("0.01"))
    discount_total += order_discount_value
    net = subtotal - discount_total

    for line in lines:
        share = (Decimal(line.line_total) / net_after_lines) if net_after_lines else ZERO
        line_net_after_order = Decimal(line.line_total) - order_discount_value * share
        tax_total += (line_net_after_order * Decimal(line.tax_percent) / HUNDRED).quantize(
            Decimal("0.01")
        )

    breakdown = score_quotation(
        lines=risk_inputs,
        tier_ceiling=tier_ceiling,
        order_discount_percent=order_discount,
        config=RiskConfigData.from_model(RiskConfig.get_solo()),
    )

    quotation.subtotal = subtotal
    quotation.discount_total = discount_total
    quotation.tax_total = tax_total
    quotation.total = net + tax_total
    quotation.margin_amount = net - cost_total
    quotation.margin_percent = ((net - cost_total) / net * HUNDRED).quantize(
        Decimal("0.01")
    ) if net else ZERO
    quotation.blended_risk_score = breakdown.score
    quotation.risk_band = breakdown.band
    quotation.requires_approval = breakdown.requires_approval
    quotation.save()
    return quotation


def risk_breakdown(quotation: Quotation):
    """Recompute the breakdown for display without saving. Screen 6 uses this."""
    ceilings = _ceiling_map()
    tier_ceiling = _tier_ceiling(quotation.customer.tier)
    inputs = [
        LineInput(
            line_id=line.id,
            label=f"{line.description} ({line.product.category.name})",
            line_subtotal=Decimal(line.line_subtotal),
            discount_percent=Decimal(line.discount_percent),
            category_ceiling=ceilings.get(line.product.category_id, tier_ceiling),
        )
        for line in quotation.lines.select_related("product", "product__category")
    ]
    return score_quotation(
        inputs,
        tier_ceiling,
        Decimal(quotation.order_discount_percent),
        RiskConfigData.from_model(RiskConfig.get_solo()),
    )


# --------------------------------------------------------------------------
# Mutations
# --------------------------------------------------------------------------
def next_quotation_number() -> str:
    last = Quotation.objects.order_by("-id").values_list("number", flat=True).first()
    seq = int(last.split("-")[1]) + 1 if last and "-" in last else 1001
    return f"Q-{seq}"


@transaction.atomic
def create_quotation(*, customer, owner_rep, price_list=None) -> Quotation:
    quotation = Quotation.objects.create(
        number=next_quotation_number(),
        customer=customer,
        owner_rep=owner_rep,
        price_list=price_list or customer.default_price_list,
        currency=customer.currency,
    )
    record_event(quotation, QuotationEventType.CREATED, actor=owner_rep)
    return quotation


@transaction.atomic
def add_line(
    quotation: Quotation,
    *,
    product_id: int,
    quantity: Decimal = Decimal("1"),
    discount_percent: Decimal = ZERO,
    variant_id: int | None = None,
    actor=None,
    from_upsell: bool = False,
) -> Quotation:
    """Add a product to the quote.

    The upsell panel calls this exact function — there is no separate 'add
    suggestion' path, which is why the margin indicator can never disagree
    with the cart.
    """
    _assert_editable(quotation)
    try:
        product = Product.objects.select_related("category", "recurring_plan").get(
            pk=product_id, is_active=True
        )
    except Product.DoesNotExist:
        raise NotFound("Product not found")

    variant = None
    if variant_id:
        variant = ProductVariant.objects.filter(pk=variant_id, product=product).first()
        if variant is None:
            raise ValidationError("That variant does not belong to this product")

    unit_price = resolve_unit_price(product, quotation.price_list, variant)
    line = QuotationLine.objects.create(
        quotation=quotation,
        product=product,
        variant=variant,
        line_type=LineType.RECURRING if product.is_subscription else LineType.ONE_TIME,
        description=product.name,
        quantity=quantity,
        unit_price=unit_price,
        unit_cost=product.cost_price,
        discount_percent=discount_percent,
        tax_percent=product.tax_percent,
        recurring_plan=product.recurring_plan,
        position=quotation.lines.count(),
    )
    recalculate(quotation)
    record_event(
        quotation,
        QuotationEventType.UPSELL_ADDED if from_upsell else QuotationEventType.LINE_ADDED,
        actor=actor,
        line_id=line.id,
        product=product.name,
        quantity=str(quantity),
    )
    return quotation


@transaction.atomic
def update_line(
    quotation: Quotation,
    line_id: int,
    *,
    quantity: Decimal | None = None,
    discount_percent: Decimal | None = None,
    actor=None,
) -> Quotation:
    _assert_editable(quotation)
    try:
        line = quotation.lines.get(pk=line_id)
    except QuotationLine.DoesNotExist:
        raise NotFound("Line not found")

    before = {"quantity": str(line.quantity), "discount_percent": str(line.discount_percent)}
    if quantity is not None:
        if quantity <= 0:
            raise ValidationError("Quantity must be greater than zero")
        line.quantity = quantity
    if discount_percent is not None:
        if not (ZERO <= discount_percent <= HUNDRED):
            raise ValidationError("Discount must be between 0 and 100 percent")
        line.discount_percent = discount_percent
    line.save()

    recalculate(quotation)
    record_event(
        quotation,
        QuotationEventType.DISCOUNT_CHANGED
        if discount_percent is not None
        else QuotationEventType.LINE_UPDATED,
        actor=actor,
        line_id=line.id,
        before=before,
        after={"quantity": str(line.quantity), "discount_percent": str(line.discount_percent)},
    )
    return quotation


@transaction.atomic
def remove_line(quotation: Quotation, line_id: int, *, actor=None) -> Quotation:
    _assert_editable(quotation)
    line = quotation.lines.filter(pk=line_id).first()
    if line is None:
        raise NotFound("Line not found")
    description = line.description
    line.delete()
    recalculate(quotation)
    record_event(
        quotation, QuotationEventType.LINE_REMOVED, actor=actor, product=description
    )
    return quotation


@transaction.atomic
def submit(quotation: Quotation, *, actor=None) -> Quotation:
    """Submit for approval — or auto-approve if every line is within limits.

    The rep never chooses. That's the point: routing is the system's job.
    """
    if not quotation.lines.exists():
        raise ValidationError("Cannot submit an empty quotation")
    recalculate(quotation)

    if not quotation.requires_approval:
        transition(quotation, QuotationStatus.APPROVED, actor=actor)
        # Clearing every ceiling is an approval too — it just didn't need a
        # human. Recording it here means these terms survive being sent.
        mark_terms_approved(quotation)
        record_event(
            quotation,
            QuotationEventType.AUTO_APPROVED,
            actor=actor,
            note="Within all tier and category ceilings.",
            score=str(quotation.blended_risk_score),
        )
        return quotation

    # Circular-import-safe: approvals depends on quotations, not vice versa.
    from apps.approvals.services import open_approval_request

    transition(quotation, QuotationStatus.PENDING_APPROVAL, actor=actor)
    open_approval_request(quotation, actor=actor)
    record_event(
        quotation,
        QuotationEventType.SUBMITTED,
        actor=actor,
        score=str(quotation.blended_risk_score),
        band=quotation.risk_band,
    )
    return quotation


@transaction.atomic
def confirm(quotation: Quotation, *, actor=None) -> dict:
    """Confirm the order: fulfillment + subscription records, in one step.

    Deliberately does NOT bill. A confirmed deal still has to be signed off by
    Finance or a Sales Manager, and raising the paperwork before that means
    billing a customer for terms nobody internal has accepted yet. The invoice
    is raised by `billing.raise_bill_for_quotation`.

    This is the seam where all three lanes meet, so it lives here and calls
    outward rather than each lane reaching in. Imports are local because
    fulfillment/subscriptions/billing all import quotations, not vice versa.

    Returns a summary the API and the demo script can both read.
    """
    from apps.fulfillment import services as fulfillment
    from apps.subscriptions import services as subscriptions

    if not quotation.lines.exists():
        raise ValidationError("Cannot confirm an empty quotation")
    if quotation.status == QuotationStatus.PENDING_APPROVAL:
        # Guarded explicitly: without this the re-approval branch below would
        # attempt PENDING_APPROVAL -> PENDING_APPROVAL and surface a confusing
        # self-transition error instead of saying what's actually wrong.
        raise InvalidTransition(
            "This quotation is still awaiting approval and cannot be confirmed yet",
            current_status=quotation.status,
        )

    # A counter-offer may have pushed this back over a ceiling while it sat in
    # the portal. Re-score before committing rather than trusting the old band.
    recalculate(quotation)
    # Approval attaches to the TERMS as well as to the status.
    #
    # `status == APPROVED` alone was the whole test, and it is still necessary:
    # APPROVED -> PENDING_APPROVAL is not a legal transition, so re-approving
    # from there raises rather than reopening anything.
    #
    # But it was not sufficient. `send_to_customer` moves an approved quote
    # APPROVED -> SENT, so the approval was thrown away the instant the offer
    # went out: a discount that Sales Manager and Finance had both signed off
    # went to the customer, and the customer accepting it put the identical
    # figures straight back in the queue for the same two people. A discount
    # only ever reaches a customer after approval, so their yes is the last one
    # needed and the order should go to fulfillment.
    already_cleared = (
        quotation.status == QuotationStatus.APPROVED or terms_are_approved(quotation)
    )
    if quotation.requires_approval and not already_cleared:
        transition(quotation, QuotationStatus.PENDING_APPROVAL, actor=actor)
        from apps.approvals.services import open_approval_request

        open_approval_request(quotation, actor=actor)
        record_event(
            quotation,
            QuotationEventType.SUBMITTED,
            actor=actor,
            note="Final terms exceed approval thresholds; re-entered approval.",
            score=str(quotation.blended_risk_score),
        )
        return {"confirmed": False, "reason": "re-entered approval", "quotation": quotation}

    transition(quotation, QuotationStatus.CONFIRMED, actor=actor)

    plan = fulfillment.suggest_plan(quotation)
    # Subscription records exist from here so the schedule is visible, but the
    # first invoice waits for the same sign-off as the one-time lines.
    created_subscriptions = subscriptions.activate_from_quotation(
        quotation, actor=actor, issue_invoices=False
    )

    record_event(
        quotation,
        QuotationEventType.CONFIRMED,
        actor=actor,
        fulfillment_plan_id=plan.id,
        subscriptions=len(created_subscriptions),
    )
    return {
        "confirmed": True,
        "quotation": quotation,
        "fulfillment_plan_id": plan.id,
        "subscription_ids": [s.id for s in created_subscriptions],
        # Always None now. Confirming no longer bills — Finance or a Sales
        # Manager raises the bill afterwards. Kept in the payload so existing
        # callers keep the same shape rather than a KeyError.
        "invoice_id": None,
    }


def chain_for(quotation: Quotation) -> list[str]:
    """The ordered approver roles for this quotation's band, read from config."""
    from apps.governance.risk import chain_for_band

    return chain_for_band(quotation.risk_band, list(ApprovalRule.objects.filter(is_active=True)))


def assert_editable(quotation: Quotation) -> None:
    """Public alias — other routers need this guard too."""
    _assert_editable(quotation)


def _assert_editable(quotation: Quotation) -> None:
    # REJECTED is deliberately NOT here. A closed deal is finished: reopening it
    # by editing the lines would silently resurrect a quotation the approver or
    # the customer had already refused, under the same number and with the
    # rejection still sitting in its audit trail. If the deal is back on, it is a
    # new quotation.
    # DRAFT only. While a quotation is UNDER_NEGOTIATION the terms are what the
    # two sides are arguing about, and they move by accept or counter - both of
    # which set order_discount_percent directly. Hand-editing a line underneath
    # a live counter-offer would change the thing being negotiated without the
    # other side seeing it, and the customer would be answering a quote that no
    # longer exists.
    editable = {QuotationStatus.DRAFT}
    if quotation.status not in editable:
        raise InvalidTransition(
            f"A quotation in {quotation.status} cannot be edited",
            current_status=quotation.status,
        )
