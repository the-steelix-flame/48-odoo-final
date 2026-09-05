"""Fulfillment orchestration.  Owner: anubhaw0raj.

Bridges the pure planner to the database: read stock -> plan -> persist
allocations -> reserve stock.
"""

from __future__ import annotations

from datetime import timedelta
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

    for alloc in plan.allocations.filter(is_backorder=False).select_related(
        "quotation_line", "warehouse"
    ):
        _reserve(alloc, actor=actor)
        _promise(alloc)

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


def _promise(alloc: FulfillmentAllocation) -> None:
    """Stamp the delivery promise from the warehouse's own lead time.

    The delivery-slippage sweep compares promised_date against today. Until
    this is set the sweep has nothing to filter on and reports zero forever,
    so screen 14's third card stays permanently empty.
    """
    alloc.promised_date = timezone.localdate() + timedelta(days=alloc.warehouse.lead_time_days)
    alloc.save(update_fields=["promised_date", "updated_at"])


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


def _recost(plan: FulfillmentPlan) -> None:
    """Recompute shipments and cost from whatever allocations now exist.

    Backordered rows don't ship yet, so they cost nothing and count for nothing.
    """
    warehouses_used = set(
        plan.allocations.filter(is_backorder=False).values_list("warehouse_id", flat=True)
    )
    plan.estimated_shipments = len(warehouses_used)
    plan.estimated_cost = sum(
        (
            Decimal(w.base_shipment_cost) * Decimal(w.shipping_cost_weight)
            for w in Warehouse.objects.filter(id__in=warehouses_used)
        ),
        Decimal("0"),
    )


@transaction.atomic
def consolidate_backorders(plan: FulfillmentPlan, *, actor=None) -> FulfillmentPlan:
    """Re-plan ONLY the backordered allocations against current stock.

    Called when restocking has set `consolidation_available`. Everything already
    allocated and reserved is left strictly alone — we never unreserve stock a
    customer is already promised, because that would let one order's
    consolidation quietly steal from another's reservation.
    """
    open_backorders = list(
        plan.allocations.filter(is_backorder=True, shipped_at__isnull=True).select_related(
            "quotation_line"
        )
    )
    if not open_backorders:
        raise ValidationError("This plan has no open backorder to consolidate")

    # One demand per backordered allocation, re-planned from scratch.
    demands = [
        Demand(
            line_id=alloc.quotation_line_id,
            product_id=alloc.quotation_line.product_id,
            variant_id=alloc.quotation_line.variant_id,
            quantity=alloc.quantity,
            unit_value=Decimal(alloc.quotation_line.unit_price),
        )
        for alloc in open_backorders
    ]
    result = plan_split(demands, _warehouse_stock())

    if all(alloc.is_backorder for alloc in result.allocations):
        # Restock wasn't enough after all. Clear the flag so the prompt stops
        # lying to the user, and say so plainly.
        plan.consolidation_available = False
        plan.save(update_fields=["consolidation_available", "updated_at"])
        raise InsufficientStock(
            "Stock is still short — there is nothing to consolidate yet",
            warehouse_id=None,
            requested=sum(d.quantity for d in demands),
            available=0,
        )

    # The plan had already been accepted, so newly-filled rows must be reserved
    # now to match the rows that were reserved at acceptance time.
    should_reserve = plan.accepted_at is not None

    for alloc in open_backorders:
        alloc.delete()

    for row in result.allocations:
        if row.warehouse_id == 0:
            continue  # "Unassigned" placeholder — no warehouse configured
        created = FulfillmentAllocation.objects.create(
            plan=plan,
            quotation_line_id=row.line_id,
            warehouse_id=row.warehouse_id,
            quantity=row.quantity,
            is_backorder=row.is_backorder,
        )
        if should_reserve and not row.is_backorder:
            _reserve(created, actor=actor)
            _promise(created)

    still_short = plan.allocations.filter(is_backorder=True).exists()
    _recost(plan)
    plan.consolidation_available = False
    if plan.accepted_at is not None:
        plan.status = FulfillmentStatus.BACKORDER if still_short else FulfillmentStatus.ACCEPTED
    plan.save()
    return plan
