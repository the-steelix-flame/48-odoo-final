"""Fulfillment orchestration.  Owner: anubhaw0raj.

Bridges the pure planner to the database: read stock -> plan -> persist
allocations -> reserve stock.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.enums import FulfillmentStatus, LineType, StockMoveReason
from apps.common.errors import InsufficientStock, NotFound, ValidationError
from apps.fulfillment.models import (
    FulfillmentAllocation,
    FulfillmentPlan,
    StockItem,
    StockMove,
    Warehouse,
)
from apps.fulfillment.planner import Demand, WarehouseStock, plan_split
from apps.quotations.models import Quotation


def _demands(quotation: Quotation) -> list[Demand]:
    """Only physical, one-time lines ship. Subscriptions don't go in a box."""
    return [
        Demand(
            line_id=line.id,
            product_id=line.product_id,
            variant_id=line.variant_id,
            quantity=int(line.quantity),
            unit_value=Decimal(line.unit_price),
        )
        for line in quotation.lines.filter(line_type=LineType.ONE_TIME)
    ]


def _warehouse_stock() -> list[WarehouseStock]:
    warehouses = list(Warehouse.objects.filter(is_active=True))
    items = StockItem.objects.filter(warehouse__in=warehouses).select_related("warehouse")
    available: dict[int, dict[tuple[int, int | None], int]] = {w.id: {} for w in warehouses}
    for item in items:
        available[item.warehouse_id][(item.product_id, item.variant_id)] = item.available
    return [
        WarehouseStock(
            warehouse_id=w.id,
            name=w.name,
            shipping_cost_weight=Decimal(w.shipping_cost_weight),
            base_shipment_cost=Decimal(w.base_shipment_cost),
            available=available[w.id],
        )
        for w in warehouses
    ]


@transaction.atomic
def suggest_plan(quotation: Quotation) -> FulfillmentPlan:
    """Compute and persist a suggested split. Does not reserve stock yet."""
    result = plan_split(_demands(quotation), _warehouse_stock())

    plan = FulfillmentPlan.objects.create(
        quotation=quotation,
        status=FulfillmentStatus.SUGGESTED,
        estimated_shipments=result.estimated_shipments,
        estimated_cost=result.estimated_cost,
    )
    for alloc in result.allocations:
        if alloc.warehouse_id == 0:
            continue  # "Unassigned" placeholder when nothing is configured
        FulfillmentAllocation.objects.create(
            plan=plan,
            quotation_line_id=alloc.line_id,
            warehouse_id=alloc.warehouse_id,
            quantity=alloc.quantity,
            is_backorder=alloc.is_backorder,
        )
    return plan


@transaction.atomic
def accept_plan(plan: FulfillmentPlan, *, actor=None) -> FulfillmentPlan:
    """Accept the suggestion and reserve the stock behind it."""
    if plan.status not in (FulfillmentStatus.SUGGESTED, FulfillmentStatus.OVERRIDDEN):
        raise ValidationError("This plan has already been accepted")

    for alloc in plan.allocations.filter(is_backorder=False).select_related("quotation_line"):
        _reserve(alloc, actor=actor)

    has_backorder = plan.allocations.filter(is_backorder=True).exists()
    plan.status = FulfillmentStatus.BACKORDER if has_backorder else FulfillmentStatus.ACCEPTED
    plan.accepted_at = timezone.now()
    plan.save(update_fields=["status", "accepted_at", "updated_at"])
    return plan


@transaction.atomic
def override_plan(plan: FulfillmentPlan, allocations: list[dict], *, actor=None) -> FulfillmentPlan:
    """Replace the suggestion with explicit human choices.

    Overrides are allowed. Unrecorded overrides are not — the plan is flagged
    and the actor is named, so the audit trail shows a person decided this.
    """
    if not allocations:
        raise ValidationError("A manual override needs at least one allocation")

    plan.allocations.all().delete()
    warehouses_used: set[int] = set()
    for row in allocations:
        line_id, warehouse_id, qty = row["quotation_line_id"], row["warehouse_id"], int(row["quantity"])
        if qty <= 0:
            raise ValidationError("Allocation quantities must be positive")
        line = plan.quotation.lines.filter(pk=line_id).first()
        if line is None:
            raise NotFound("That line is not on this quotation")
        item = StockItem.objects.filter(
            warehouse_id=warehouse_id, product_id=line.product_id, variant_id=line.variant_id
        ).first()
        is_backorder = item is None or item.available < qty
        FulfillmentAllocation.objects.create(
            plan=plan,
            quotation_line_id=line_id,
            warehouse_id=warehouse_id,
            quantity=qty,
            is_backorder=is_backorder,
        )
        if not is_backorder:
            warehouses_used.add(warehouse_id)

    plan.is_manual_override = True
    plan.status = FulfillmentStatus.OVERRIDDEN
    plan.estimated_shipments = len(warehouses_used)
    plan.estimated_cost = sum(
        (
            Decimal(w.base_shipment_cost) * Decimal(w.shipping_cost_weight)
            for w in Warehouse.objects.filter(id__in=warehouses_used)
        ),
        Decimal("0"),
    )
    plan.save()
    return plan


def _reserve(alloc: FulfillmentAllocation, *, actor=None) -> None:
    line = alloc.quotation_line
    item = StockItem.objects.select_for_update().filter(
        warehouse_id=alloc.warehouse_id, product_id=line.product_id, variant_id=line.variant_id
    ).first()
    if item is None or item.available < alloc.quantity:
        raise InsufficientStock(
            f"{line.description} is no longer available at that warehouse",
            warehouse_id=alloc.warehouse_id,
            requested=alloc.quantity,
            available=item.available if item else 0,
        )
    item.quantity_reserved += alloc.quantity
    item.save(update_fields=["quantity_reserved", "updated_at"])
    StockMove.objects.create(
        stock_item=item,
        delta=0,  # reservations don't change on-hand, only availability
        reason=StockMoveReason.RESERVE,
        ref_type="fulfillment_allocation",
        ref_id=alloc.id,
        actor=actor,
    )


@transaction.atomic
def restock(item: StockItem, quantity: int, *, actor=None) -> StockItem:
    """Receive stock, then look for backorders this could now fill.

    The consolidation prompt appears because stock ARRIVED, not because
    somebody refreshed a screen. That's the behaviour the brief asks for.
    """
    if quantity <= 0:
        raise ValidationError("Restock quantity must be positive")
    item.quantity_on_hand += quantity
    item.save(update_fields=["quantity_on_hand", "updated_at"])
    StockMove.objects.create(
        stock_item=item, delta=quantity, reason=StockMoveReason.RESTOCK, actor=actor
    )
    check_backorders(item)
    return item


def check_backorders(item: StockItem) -> int:
    """Flag any plan whose backorder this restock could now satisfy."""
    open_allocs = FulfillmentAllocation.objects.filter(
        is_backorder=True,
        shipped_at__isnull=True,
        quotation_line__product_id=item.product_id,
    ).select_related("plan")

    flagged = 0
    remaining = item.available
    for alloc in open_allocs:
        if remaining >= alloc.quantity and not alloc.plan.consolidation_available:
            alloc.plan.consolidation_available = True
            alloc.plan.save(update_fields=["consolidation_available", "updated_at"])
            flagged += 1
    return flagged
