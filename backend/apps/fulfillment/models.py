from django.db import models

from apps.common.enums import FulfillmentStatus, StockMoveReason
from apps.common.models import MONEY, TimeStampedModel, money


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True)
    address = models.CharField(max_length=250, blank=True)
    #: Cost multiplier the splitter uses to break ties. Main = 1.0, remote = 1.4.
    shipping_cost_weight = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    base_shipment_cost = models.DecimalField(**money(default=30))
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "warehouse"
        ordering = ["shipping_cost_weight", "name"]

    def __str__(self) -> str:
        return self.name


class StockItem(TimeStampedModel):
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="stock_items"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="stock_items"
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    quantity_on_hand = models.IntegerField(default=0)
    quantity_reserved = models.IntegerField(default=0)
    reorder_point = models.IntegerField(default=0)
    reorder_quantity = models.IntegerField(default=0)

    class Meta:
        db_table = "stock_item"
        unique_together = [("warehouse", "product", "variant")]

    def __str__(self) -> str:
        return f"{self.product.name} @ {self.warehouse.name}: {self.available} available"

    @property
    def available(self) -> int:
        """Screen 7's third column. Computed, never stored."""
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def needs_replenishment(self) -> bool:
        return self.available <= self.reorder_point


class StockMove(TimeStampedModel):
    """Append-only ledger. `quantity_on_hand` is the running total; this is
    how we prove it, and how a RESTOCK triggers the backorder-consolidation
    prompt without anyone having to refresh a screen."""

    stock_item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="moves")
    delta = models.IntegerField(help_text="Signed change to quantity_on_hand")
    reason = models.CharField(max_length=12, choices=StockMoveReason.choices)
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.IntegerField(null=True, blank=True)
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "stock_move"
        ordering = ["-created_at"]


class FulfillmentPlan(TimeStampedModel):
    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="fulfillment_plans"
    )
    status = models.CharField(
        max_length=20, choices=FulfillmentStatus.choices, default=FulfillmentStatus.SUGGESTED
    )
    estimated_shipments = models.IntegerField(default=0)
    estimated_cost = models.DecimalField(**MONEY)
    is_manual_override = models.BooleanField(default=False)
    #: Set when a RESTOCK makes an open backorder fillable — screen 8 shows the
    #: "Consolidate Remaining Backorder" prompt when this is true.
    consolidation_available = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fulfillment_plan"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.quotation.number} → {self.estimated_shipments} shipment(s)"


class FulfillmentAllocation(TimeStampedModel):
    plan = models.ForeignKey(
        FulfillmentPlan, on_delete=models.CASCADE, related_name="allocations"
    )
    quotation_line = models.ForeignKey(
        "quotations.QuotationLine", on_delete=models.CASCADE, related_name="allocations"
    )
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="allocations")
    quantity = models.IntegerField()
    is_backorder = models.BooleanField(default=False)
    #: promised_date vs shipped_at is what the delivery-slippage alert compares.
    promised_date = models.DateField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fulfillment_allocation"

    def __str__(self) -> str:
        tag = " (backorder)" if self.is_backorder else ""
        return f"{self.quantity} × {self.quotation_line.description} from {self.warehouse.name}{tag}"
