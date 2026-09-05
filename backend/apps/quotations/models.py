from django.db import models
from django.utils import timezone

from apps.common.enums import (
    LineType,
    QuotationEventType,
    QuotationStatus,
    RiskBand,
)
from apps.common.models import MONEY, PERCENT, QUANTITY, TimeStampedModel


class Quotation(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="quotations"
    )
    owner_rep = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="quotations"
    )
    price_list = models.ForeignKey(
        "catalog.PriceList", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(
        max_length=24, choices=QuotationStatus.choices, default=QuotationStatus.DRAFT
    )

    #: Applied on top of line-level discounts.
    order_discount_percent = models.DecimalField(**PERCENT)

    # Recomputed by services.recalculate() on every write. Never trusted from
    # the client, never computed in a template.
    subtotal = models.DecimalField(**MONEY)
    discount_total = models.DecimalField(**MONEY)
    tax_total = models.DecimalField(**MONEY)
    total = models.DecimalField(**MONEY)
    margin_amount = models.DecimalField(**MONEY)
    margin_percent = models.DecimalField(**PERCENT)

    blended_risk_score = models.DecimalField(**PERCENT)
    risk_band = models.CharField(max_length=10, choices=RiskBand.choices, default=RiskBand.NONE)
    requires_approval = models.BooleanField(default=False)

    valid_until = models.DateField(null=True, blank=True)
    #: Stalled-deal detection reads this. Touched by every audited write.
    last_activity_at = models.DateTimeField(default=timezone.now)
    #: Set when the customer accepts our counter-offer. If the agreed terms then
    #: need approval, the approvers are the only ones left to decide — the
    #: customer has already committed, so clearing approval confirms the order
    #: rather than sending it back for a second yes.
    customer_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "quotation"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["owner_rep", "status"]),
            models.Index(fields=["last_activity_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.number} — {self.customer.name}"

    @property
    def one_time_lines(self):
        return self.lines.filter(line_type=LineType.ONE_TIME)

    @property
    def recurring_lines(self):
        return self.lines.filter(line_type=LineType.RECURRING)

    @property
    def idle_days(self) -> int:
        return (timezone.now() - self.last_activity_at).days


class QuotationLine(TimeStampedModel):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    line_type = models.CharField(
        max_length=12, choices=LineType.choices, default=LineType.ONE_TIME
    )
    #: Snapshot of the product name — renaming a product later must not rewrite
    #: what the customer was quoted.
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(**QUANTITY)
    unit_price = models.DecimalField(**MONEY)
    unit_cost = models.DecimalField(**MONEY)
    discount_percent = models.DecimalField(**PERCENT)

    # The governance verdict, STORED not derived. Ceilings change over time;
    # the approval screen must be able to show why this quote was flagged then.
    allowed_discount_percent = models.DecimalField(**PERCENT)
    discount_excess_points = models.DecimalField(**PERCENT)

    tax_percent = models.DecimalField(**PERCENT)
    line_subtotal = models.DecimalField(**MONEY)  # qty × price, before discount
    line_total = models.DecimalField(**MONEY)  # after discount, before order-level
    margin_amount = models.DecimalField(**MONEY)

    recurring_plan = models.ForeignKey(
        "subscriptions.RecurringPlan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    position = models.IntegerField(default=0)

    class Meta:
        db_table = "quotation_line"
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return f"{self.description} × {self.quantity}"

    @property
    def is_over_limit(self) -> bool:
        return self.discount_excess_points > 0


class QuotationEvent(TimeStampedModel):
    """Append-only audit trail. Screens 6 and 14 both read this table."""

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    event_type = models.CharField(max_length=24, choices=QuotationEventType.choices)
    payload = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_event"
        ordering = ["created_at"]

    def __str__(self) -> str:
        who = self.actor.full_name if self.actor else "system"
        return f"{self.quotation_id} {self.event_type} by {who}"
