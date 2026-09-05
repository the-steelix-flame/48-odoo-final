"""Subscription lifecycle.  Owner: anubhaw0raj.

Bridges the pure proration module to the database and to billing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing import services as billing
from apps.common.enums import (
    CancellationPolicy,
    LineType,
    SubscriptionEventType,
    SubscriptionStatus,
)
from apps.common.errors import ValidationError
from apps.quotations.models import Quotation
from apps.subscriptions.models import RecurringPlan, Subscription, SubscriptionEvent
from apps.subscriptions.proration import (
    Period,
    cancellation_refund,
    next_period,
    quantity_change,
)


def _period_of(subscription: Subscription) -> Period:
    return Period(subscription.current_period_start, subscription.current_period_end)


@transaction.atomic
def activate_from_quotation(quotation: Quotation, *, actor=None) -> list[Subscription]:
    """Turn every RECURRING line on a confirmed order into a subscription.

    Each one gets its own billing schedule, separate from the order's one-time
    invoice. That's hybrid billing: same order, two lifecycles.
    """
    created: list[Subscription] = []
    today = timezone.now().date()

    for line in quotation.lines.filter(line_type=LineType.RECURRING).select_related(
        "product", "recurring_plan"
    ):
        plan: RecurringPlan | None = line.recurring_plan or line.product.recurring_plan
        if plan is None:
            raise ValidationError(
                f"{line.description} is a recurring line but has no plan attached"
            )

        period = next_period(today, plan.interval)
        subscription = Subscription.objects.create(
            customer=quotation.customer,
            quotation=quotation,
            quotation_line=line,
            plan=plan,
            product=line.product,
            quantity=line.quantity,
            # Net of the discount the rep gave — the subscription inherits the
            # negotiated price, not the list price.
            unit_price=Decimal(line.line_total) / Decimal(line.quantity),
            start_date=today,
            current_period_start=period.start,
            current_period_end=period.end,
            next_bill_date=period.end,
        )
        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEventType.CREATED,
            effective_date=today,
            new_quantity=line.quantity,
            proration_amount=Decimal("0"),
            actor=actor,
            note=f"Created from {quotation.number}",
        )
        if plan.bill_in_advance:
            billing.issue_recurring_invoice(subscription, period.start, period.end)
        created.append(subscription)

    return created


@transaction.atomic
def change_quantity(
    subscription: Subscription,
    new_quantity: Decimal,
    *,
    effective_date: date | None = None,
    actor=None,
) -> SubscriptionEvent:
    """Mid-cycle quantity change → prorated invoice or credit note.

    One signed formula drives both directions, which is why an upgrade and a
    downgrade of the same size always agree.
    """
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise ValidationError("Only an active subscription can be changed")
    new_quantity = Decimal(new_quantity)
    if new_quantity <= 0:
        raise ValidationError("Quantity must be positive — cancel the subscription instead")

    effective_date = effective_date or timezone.now().date()
    old_quantity = Decimal(subscription.quantity)

    result = quantity_change(
        period=_period_of(subscription),
        effective_date=effective_date,
        unit_price=Decimal(subscription.unit_price),
        old_quantity=old_quantity,
        new_quantity=new_quantity,
        proration_mode=subscription.plan.proration_mode,
    )

    subscription.quantity = new_quantity
    subscription.save(update_fields=["quantity", "updated_at"])

    invoice = credit_note = None
    if result.is_charge:
        invoice = billing.issue_proration_invoice(
            subscription, result.amount, f"Proration — {result.description}"
        )
    elif result.is_credit:
        credit_note = billing.issue_credit_note(
            subscription.customer, result.amount, f"Proration — {result.description}"
        )

    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=SubscriptionEventType.QUANTITY_CHANGED,
        effective_date=effective_date,
        old_quantity=old_quantity,
        new_quantity=new_quantity,
        proration_amount=result.amount,
        invoice=invoice,
        credit_note=credit_note,
        actor=actor,
        note=result.description,
    )


@transaction.atomic
def cancel(
    subscription: Subscription, *, effective_date: date | None = None, actor=None
) -> SubscriptionEvent:
    """Cancel, honouring the plan's policy and refund mode."""
    if subscription.status == SubscriptionStatus.CANCELLED:
        raise ValidationError("This subscription is already cancelled")

    plan = subscription.plan
    effective_date = effective_date or timezone.now().date()
    credit_note = None
    amount = Decimal("0")

    if plan.cancellation_policy == CancellationPolicy.END_OF_PERIOD:
        # Stays active until the period ends; nothing to refund.
        subscription.cancellation_effective_date = subscription.current_period_end
        subscription.next_bill_date = None
        note = f"Cancels at end of period ({subscription.current_period_end})."
    else:
        result = cancellation_refund(
            period=_period_of(subscription),
            effective_date=effective_date,
            period_amount=Decimal(subscription.period_amount),
            refund_mode=plan.refund_mode,
            proration_mode=plan.proration_mode,
        )
        amount = result.amount
        note = result.description
        if result.is_credit:
            credit_note = billing.issue_credit_note(
                subscription.customer, result.amount, f"Cancellation refund — {note}"
            )
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = timezone.now()
        subscription.cancellation_effective_date = effective_date
        subscription.next_bill_date = None

    subscription.save()
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=SubscriptionEventType.CANCELLED,
        effective_date=effective_date,
        old_quantity=subscription.quantity,
        proration_amount=amount,
        credit_note=credit_note,
        actor=actor,
        note=note,
    )


@transaction.atomic
def renew(subscription: Subscription) -> SubscriptionEvent | None:
    """Roll the period forward and issue the next invoice.

    Called by `manage.py run_billing`. In production this is a nightly beat;
    as a command it also lets the demo time-travel.
    """
    if subscription.status != SubscriptionStatus.ACTIVE or subscription.next_bill_date is None:
        return None

    period = next_period(subscription.current_period_end, subscription.plan.interval)
    subscription.current_period_start = period.start
    subscription.current_period_end = period.end
    subscription.next_bill_date = period.end
    subscription.save(
        update_fields=[
            "current_period_start", "current_period_end", "next_bill_date", "updated_at",
        ]
    )
    invoice = billing.issue_recurring_invoice(subscription, period.start, period.end)
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=SubscriptionEventType.RENEWED,
        effective_date=period.start,
        proration_amount=invoice.total,
        invoice=invoice,
        note=f"Renewed for {period.start} → {period.end}",
    )
