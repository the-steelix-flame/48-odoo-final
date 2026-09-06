"""Warehouse administration.  Owner: the-steelix-flame.

A warehouse is where stock physically sits, and defining one is an admin act:
it decides what the fulfillment splitter is even allowed to consider. Until now
there was no way to create one outside `seed_demo` and the Django admin, so a
demo could not add a depot at all.

NOTE FOR @anubhaw0raj: `Warehouse` is your model. This adds three nullable
columns and nothing else — `planner.py` and `fulfillment/services.py` are
untouched and still rank by `shipping_cost_weight`. This is a NEW file in
`accounts` (same reasoning as `businesses.py` and `plans.py`) so the admin
surface stays in one lane and never conflicts with `fulfillment/`.

`latitude`/`longitude` exist for the distance-based allocation described in
`PLAN-distance-fulfillment.md`. Nothing reads them yet. They are enterable by
hand now and will be filled from `address` by the geocoder in Phase 2.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.common.errors import NotFound, ValidationError
from apps.common.geo import clean_point
from apps.fulfillment.models import Warehouse


def queryset() -> QuerySet[Warehouse]:
    """Every warehouse, retired ones included. An admin who cannot see a
    retired warehouse cannot bring it back."""
    return Warehouse.objects.all().order_by("-is_active", "name")


def get_warehouse(warehouse_id: int) -> Warehouse:
    warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
    if warehouse is None:
        raise NotFound("No such warehouse")
    return warehouse


def active_count(exclude_pk: int | None = None) -> int:
    qs = Warehouse.objects.filter(is_active=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def stock_summary(warehouse: Warehouse) -> tuple[int, int]:
    """(distinct stock lines, total units on hand).

    Shown on the row so an admin can see what retiring this warehouse would
    strand before they press the button.
    """
    items = list(warehouse.stock_items.values_list("quantity_on_hand", flat=True))
    return len(items), sum(int(q) for q in items)


# ------------------------------------------------------------------ cleaning
def _clean_name(name: str, *, exclude_pk: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("A warehouse name is required")
    clash = Warehouse.objects.filter(name__iexact=name)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise ValidationError(f"A warehouse called {name} already exists")
    return name


def _clean_code(code: str, *, exclude_pk: int | None = None) -> str:
    # Upper-cased on the way in. The column is unique and case-sensitive, so
    # "wh-1" and "WH-1" would otherwise both be accepted and read as one code.
    code = (code or "").strip().upper()
    if not code:
        raise ValidationError("A warehouse code is required")
    clash = Warehouse.objects.filter(code__iexact=code)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise ValidationError(f"The code {code} is already used by another warehouse")
    return code


def _clean_numbers(shipping_cost_weight, base_shipment_cost, lead_time_days) -> dict:
    try:
        weight = Decimal(str(shipping_cost_weight))
        cost = Decimal(str(base_shipment_cost))
        lead = int(lead_time_days)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(
            "Cost weight, shipment cost and lead time must be numbers"
        ) from None

    # The splitter multiplies by the weight and sorts on it. Zero makes every
    # warehouse look free and identical; a negative inverts the ranking.
    if weight <= 0:
        raise ValidationError("Cost weight must be greater than zero")
    if cost < 0:
        raise ValidationError("Base shipment cost cannot be negative")
    if lead < 0:
        raise ValidationError("Lead time cannot be negative")
    return {
        "shipping_cost_weight": weight,
        "base_shipment_cost": cost,
        "lead_time_days": lead,
    }


# ------------------------------------------------------------------ mutations
@transaction.atomic
def create_warehouse(
    *,
    name: str,
    code: str,
    address: str = "",
    latitude=None,
    longitude=None,
    shipping_cost_weight="1",
    base_shipment_cost="30",
    lead_time_days: int = 3,
    is_active: bool = True,
    actor: User | None = None,
) -> Warehouse:
    """Register a warehouse. Available to the splitter immediately if active."""
    lat, lng = clean_point(latitude, longitude)
    return Warehouse.objects.create(
        name=_clean_name(name),
        code=_clean_code(code),
        address=(address or "").strip(),
        latitude=lat,
        longitude=lng,
        is_active=is_active,
        **_clean_numbers(shipping_cost_weight, base_shipment_cost, lead_time_days),
    )


@transaction.atomic
def update_warehouse(warehouse: Warehouse, *, actor: User | None = None, **changes) -> Warehouse:
    """Edit a warehouse. Only the keys present in `changes` are touched."""
    if "name" in changes:
        warehouse.name = _clean_name(changes["name"], exclude_pk=warehouse.pk)
    if "code" in changes:
        warehouse.code = _clean_code(changes["code"], exclude_pk=warehouse.pk)
    if "address" in changes:
        warehouse.address = (changes["address"] or "").strip()

    # Coordinates move together, so they are validated together even when only
    # one of the two was sent — the other is read off the row as it stands.
    if "latitude" in changes or "longitude" in changes:
        lat, lng = clean_point(
            changes.get("latitude", warehouse.latitude),
            changes.get("longitude", warehouse.longitude),
        )
        warehouse.latitude, warehouse.longitude = lat, lng
        # A hand-typed correction is not a geocoding result. Clearing this is
        # what stops a later re-geocode from overwriting it.
        warehouse.geocoded_at = None

    numeric = {
        field: changes[field]
        for field in ("shipping_cost_weight", "base_shipment_cost", "lead_time_days")
        if field in changes
    }
    if numeric:
        cleaned = _clean_numbers(
            numeric.get("shipping_cost_weight", warehouse.shipping_cost_weight),
            numeric.get("base_shipment_cost", warehouse.base_shipment_cost),
            numeric.get("lead_time_days", warehouse.lead_time_days),
        )
        for field, value in cleaned.items():
            setattr(warehouse, field, value)

    if "is_active" in changes:
        warehouse.save()
        return set_active(warehouse, enabled=bool(changes["is_active"]), actor=actor)

    warehouse.save()
    return warehouse


def set_active(warehouse: Warehouse, *, enabled: bool, actor: User | None = None) -> Warehouse:
    """Retire a warehouse or bring it back. Never deletes.

    `StockItem` and `FulfillmentAllocation` both point here, so deleting would
    either cascade away real stock records or orphan the allocation history that
    says where a shipped order came from.

    Retiring the LAST active warehouse is refused: `plan_split` answers
    "No active warehouses configured" and backorders every line of every order,
    so this would break all future allocation from one click with nothing on
    screen explaining why.
    """
    if not enabled and warehouse.is_active and active_count(exclude_pk=warehouse.pk) == 0:
        raise ValidationError(
            "This is the only active warehouse. Add another before retiring it — "
            "with none active, every order goes straight to backorder."
        )
    warehouse.is_active = enabled
    warehouse.save(update_fields=["is_active", "updated_at"])
    return warehouse
