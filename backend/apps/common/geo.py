"""Coordinates, shared by every model that has an address.

Both `accounts.Customer` and `fulfillment.Warehouse` carry a point, and the
fulfillment splitter will eventually measure one against the other. Validating
them in two places would let the two drift, so the rule lives here once.

This module is deliberately dependency-free — no Django, no network. Phase 3 of
`PLAN-distance-fulfillment.md` adds `haversine_km` alongside `clean_point` so
that `planner.py` can stay the pure function it is documented to be.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.common.errors import ValidationError

#: Latitude runs -90..90 and longitude -180..180. A value outside those is not
#: a near-miss, it is a different kind of number — a swapped pair, or metres.
LAT_MIN, LAT_MAX = Decimal("-90"), Decimal("90")
LNG_MIN, LNG_MAX = Decimal("-180"), Decimal("180")


def clean_point(latitude, longitude) -> tuple[Decimal | None, Decimal | None]:
    """Validate a coordinate pair. Returns `(None, None)` when there isn't one.

    **Both or neither.** A row with a latitude and no longitude would be read as
    sitting on the prime meridian — a confidently wrong position, which is worse
    than the honest "no coordinates, fall back to the static cost weight".
    """
    if latitude in (None, "") and longitude in (None, ""):
        return None, None
    if latitude in (None, "") or longitude in (None, ""):
        raise ValidationError("Give both a latitude and a longitude, or neither")

    try:
        lat, lng = Decimal(str(latitude)), Decimal(str(longitude))
    except (InvalidOperation, ValueError):
        raise ValidationError("Latitude and longitude must be numbers") from None

    if not (LAT_MIN <= lat <= LAT_MAX):
        raise ValidationError("Latitude must be between -90 and 90")
    if not (LNG_MIN <= lng <= LNG_MAX):
        raise ValidationError("Longitude must be between -180 and 180")
    return lat, lng
