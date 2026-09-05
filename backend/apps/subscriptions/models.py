from django.db import models

from apps.common.enums import (
    CancellationPolicy,
    ProrationMode,
    RecurringInterval,
    RefundMode,
    SubscriptionEventType,
    SubscriptionStatus,
)
from apps.common.models import MONEY, QUANTITY, TimeStampedModel


class RecurringPlan(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    interval = models.CharField(
        max_length=12, choices=RecurringInterval.choices, default=RecurringInterval.MONTHLY
    )
    proration_mode = models.CharField(
        max_length=12, choices=ProrationMode.choices, default=ProrationMode.DAILY
    )
    cancellation_policy = models.CharField(
        max_length=16, choices=CancellationPolicy.choices, default=CancellationPolicy.IMMEDIATE
    )
    refund_mode = models.CharField(
        max_length=10, choices=RefundMode.choices, default=RefundMode.PRORATED
    )
    #: "Recurring order with this product will be invoiced at the beginning of
    #: the period" — screen 17's note.
    bill_in_advance = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "recurring_plan"

    def __str__(self) -> str:
        return f"{self.name} ({self.interval})"


class Subscription(TimeStampedModel):
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="subscriptions"
    )
    #: Provenance — which order created this recurring line.
    quotation = models.ForeignKey(
        "quotations.Quotation", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="subscriptions",
    )
    quotation_line = models.ForeignKey(
        "quotations.QuotationLine", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(RecurringPlan, on_delete=models.PROTECT, related_name="subscriptions")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")

    quantity = models.DecimalField(**QUANTITY)
    unit_price = models.DecimalField(**MONEY)
    status = models.CharField(
        max_length=12, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE
    )

    start_date = models.DateField()
    #: The window proration divides by.
    current_period_start = models.DateField()
    current_period_end = models.DateField()
    next_bill_date = models.DateField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_effective_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "subscription"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.customer.name} — {self.plan.name}"

    @property
    def period_amount(self):
        return self.quantity * self.unit_price


class SubscriptionEvent(TimeStampedModel):
    """The proration history shown on screen 10.

    `proration_amount` is SIGNED: positive becomes an invoice line, negative
    becomes a credit note. One rule, both directions.
    """

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=20, choices=SubscriptionEventType.choices)
    effective_date = models.DateField()
    old_quantity = models.DecimalField(**QUANTITY, null=True, blank=True)
    new_quantity = models.DecimalField(**QUANTITY, null=True, blank=True)
    proration_amount = models.DecimalField(**MONEY)
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    credit_note = models.ForeignKey(
        "billing.CreditNote", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        db_table = "subscription_event"
        ordering = ["-effective_date", "-created_at"]
