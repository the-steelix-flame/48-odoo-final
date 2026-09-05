"""Multi-warehouse split planner.  Owner: anubhaw0raj.

★ PURE FUNCTION. No database, no Django. Plain dataclasses in and out.

Objective, in strict priority order:
    1. fewest shipments   (a customer would rather get one parcel)
    2. lowest shipping cost
    3. least backorder

Step 1 is exact — if any single warehouse can cover the whole order, we always
find the cheapest such warehouse. Step 2 is greedy, which is not provably
optimal (this is bin-packing), and that's a deliberate trade: it runs in
milliseconds, it never loses to the optimal answer in the one-warehouse case,
and a human can override it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Demand:
    """One physical line that needs shipping."""

    line_id: int
    product_id: int
    variant_id: int | None
    quantity: int
    unit_value: Decimal = Decimal("0")  # used to prioritise valuable lines


@dataclass(frozen=True)
class WarehouseStock:
    warehouse_id: int
    name: str
    shipping_cost_weight: Decimal
    base_shipment_cost: Decimal
    #: {(product_id, variant_id): available_quantity}
    available: dict[tuple[int, int | None], int]


@dataclass
class Allocation:
    line_id: int
    warehouse_id: int
    warehouse_name: str
    quantity: int
    is_backorder: bool = False


@dataclass
class SplitPlan:
    allocations: list[Allocation] = field(default_factory=list)
    estimated_shipments: int = 0
    estimated_cost: Decimal = Decimal("0")
    fully_fulfilled: bool = True
    notes: str = ""


def plan_split(demands: list[Demand], warehouses: list[WarehouseStock]) -> SplitPlan:
    """Work out which warehouse ships what."""
    demands = [d for d in demands if d.quantity > 0]
    if not demands:
        return SplitPlan(notes="Nothing to ship — order has no physical lines.")
    if not warehouses:
        return SplitPlan(
            allocations=[
                Allocation(d.line_id, 0, "Unassigned", d.quantity, is_backorder=True)
                for d in demands
            ],
            fully_fulfilled=False,
            notes="No active warehouses configured.",
        )

    # --- Step 1: can one warehouse do the whole job? ----------------------
    for wh in sorted(warehouses, key=lambda w: w.shipping_cost_weight):
        if all(wh.available.get(_key(d), 0) >= d.quantity for d in demands):
            return SplitPlan(
                allocations=[
                    Allocation(d.line_id, wh.warehouse_id, wh.name, d.quantity) for d in demands
                ],
                estimated_shipments=1,
                estimated_cost=_cost(wh),
                notes=f"{wh.name} can cover the whole order — single shipment.",
            )

    # --- Step 2: greedy multi-warehouse -----------------------------------
    remaining: dict[int, int] = {d.line_id: d.quantity for d in demands}
    by_line = {d.line_id: d for d in demands}
    stock = {w.warehouse_id: dict(w.available) for w in warehouses}
    unused = {w.warehouse_id: w for w in warehouses}

    allocations: list[Allocation] = []
    chosen: list[WarehouseStock] = []

    while any(qty > 0 for qty in remaining.values()) and unused:
        best_id, best_coverage = None, Decimal("-1")
        for wh_id, wh in unused.items():
            coverage = Decimal("0")
            for line_id, qty in remaining.items():
                if qty <= 0:
                    continue
                d = by_line[line_id]
                takeable = min(stock[wh_id].get(_key(d), 0), qty)
                coverage += Decimal(takeable) * (d.unit_value or Decimal("1"))
            # Highest coverage wins; cheapest breaks the tie.
            if coverage > best_coverage or (
                coverage == best_coverage
                and best_id is not None
                and wh.shipping_cost_weight < unused[best_id].shipping_cost_weight
            ):
                best_id, best_coverage = wh_id, coverage

        if best_id is None or best_coverage <= 0:
            break  # nothing left that any remaining warehouse can help with

        wh = unused.pop(best_id)
        took_anything = False
        for line_id, qty in list(remaining.items()):
            if qty <= 0:
                continue
            d = by_line[line_id]
            takeable = min(stock[best_id].get(_key(d), 0), qty)
            if takeable > 0:
                allocations.append(Allocation(line_id, wh.warehouse_id, wh.name, takeable))
                remaining[line_id] = qty - takeable
                stock[best_id][_key(d)] = stock[best_id].get(_key(d), 0) - takeable
                took_anything = True
        if took_anything:
            chosen.append(wh)

    # --- Step 3: whatever's left is a backorder ---------------------------
    shortfall = {lid: qty for lid, qty in remaining.items() if qty > 0}
    if shortfall:
        # Park it on the cheapest warehouse; it'll be consolidated on restock.
        fallback = min(warehouses, key=lambda w: w.shipping_cost_weight)
        for line_id, qty in shortfall.items():
            allocations.append(
                Allocation(line_id, fallback.warehouse_id, fallback.name, qty, is_backorder=True)
            )

    # --- Step 4: cost -----------------------------------------------------
    cost = sum((_cost(w) for w in chosen), Decimal("0"))
    names = ", ".join(w.name for w in chosen) or "none"
    notes = f"Split across {len(chosen)} warehouse(s): {names}."
    if shortfall:
        notes += f" {sum(shortfall.values())} unit(s) on backorder pending restock."

    return SplitPlan(
        allocations=allocations,
        estimated_shipments=len(chosen),
        estimated_cost=cost,
        fully_fulfilled=not shortfall,
        notes=notes,
    )


def _key(demand: Demand) -> tuple[int, int | None]:
    return (demand.product_id, demand.variant_id)


def _cost(wh: WarehouseStock) -> Decimal:
    return (Decimal(wh.base_shipment_cost) * Decimal(wh.shipping_cost_weight)).quantize(
        Decimal("0.01")
    )
