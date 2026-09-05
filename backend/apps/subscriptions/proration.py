"""Subscription proration.  Owner: anubhaw0raj.

★ PURE FUNCTION. Dates and decimals in, a signed amount out. No database.

The whole module rests on one idea: a mid-cycle change is worth the fraction
of the period that hasn't happened yet. Charging and refunding are the same
formula with opposite signs, which is why upgrades and downgrades can never
disagree with each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal("0")


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days)

    def remaining_days(self, on: date) -> int:
        """Days left in the period, clamped to [0, days]."""
        if on <= self.start:
            return self.days
        if on >= self.end:
            return 0
        return (self.end - on).days

    def fraction_remaining(self, on: date) -> Decimal:
        return Decimal(self.remaining_days(on)) / Decimal(self.days)


@dataclass
class ProrationResult:
    #: Signed. Positive -> charge (invoice). Negative -> credit note.
    amount: Decimal
    remaining_days: int
    period_days: int
    fraction: Decimal
    description: str

    @property
    def is_charge(self) -> bool:
        return self.amount > ZERO

    @property
    def is_credit(self) -> bool:
        return self.amount < ZERO


def quantity_change(
    *,
    period: Period,
    effective_date: date,
    unit_price: Decimal,
    old_quantity: Decimal,
    new_quantity: Decimal,
    proration_mode: str = "DAILY",
) -> ProrationResult:
    """Price a mid-cycle quantity change.

    Worked example from WORKFLOW.md §6: Care Plan at $46/unit, period
    Sep 1 -> Oct 1, going 1 -> 3 units on Sep 16 gives +$46.00.
    """
    unit_price = Decimal(unit_price)
    delta = Decimal(new_quantity) - Decimal(old_quantity)
    fraction = _fraction(period, effective_date, proration_mode)
    amount = (delta * unit_price * fraction).quantize(Decimal("0.01"))

    direction = "increase" if delta > 0 else "decrease" if delta < 0 else "no change"
    return ProrationResult(
        amount=amount,
        remaining_days=period.remaining_days(effective_date),
        period_days=period.days,
        fraction=fraction,
        description=(
            f"Quantity {direction} {old_quantity} → {new_quantity} on "
            f"{effective_date.isoformat()}, {period.remaining_days(effective_date)} of "
            f"{period.days} days remaining."
        ),
    )


def plan_change(
    *,
    period: Period,
    effective_date: date,
    old_period_amount: Decimal,
    new_period_amount: Decimal,
    proration_mode: str = "DAILY",
) -> ProrationResult:
    """Credit the unused remainder of the old plan, charge the new one."""
    fraction = _fraction(period, effective_date, proration_mode)
    credit = (Decimal(old_period_amount) * fraction).quantize(Decimal("0.01"))
    charge = (Decimal(new_period_amount) * fraction).quantize(Decimal("0.01"))
    amount = charge - credit
    return ProrationResult(
        amount=amount,
        remaining_days=period.remaining_days(effective_date),
        period_days=period.days,
        fraction=fraction,
        description=(
            f"Plan change on {effective_date.isoformat()}: credited {credit} of the old plan, "
            f"charged {charge} for the new one."
        ),
    )


def cancellation_refund(
    *,
    period: Period,
    effective_date: date,
    period_amount: Decimal,
    refund_mode: str = "PRORATED",
    proration_mode: str = "DAILY",
) -> ProrationResult:
    """Refund for the unused remainder. Always <= 0 (a credit)."""
    if refund_mode == "NONE":
        return ProrationResult(
            amount=ZERO,
            remaining_days=period.remaining_days(effective_date),
            period_days=period.days,
            fraction=ZERO,
            description="Plan policy is no refund on cancellation.",
        )
    fraction = _fraction(period, effective_date, proration_mode)
    amount = -(Decimal(period_amount) * fraction).quantize(Decimal("0.01"))
    return ProrationResult(
        amount=amount,
        remaining_days=period.remaining_days(effective_date),
        period_days=period.days,
        fraction=fraction,
        description=(
            f"Cancelled on {effective_date.isoformat()} with "
            f"{period.remaining_days(effective_date)} of {period.days} days unused."
        ),
    )


def _fraction(period: Period, on: date, mode: str) -> Decimal:
    if mode == "NONE":
        return ZERO  # change applies from the next period, nothing owed now
    if mode == "FULL_PERIOD":
        return Decimal(1)  # charge/credit the whole period regardless
    return period.fraction_remaining(on)


#: Every cadence, as a number of calendar months. A table rather than an
#: if-chain because this file is the one place a cadence becomes a date: an
#: interval missing here raises on the confirm path, after the customer has
#: already said yes. Keep it in step with `RecurringInterval`; the test
#: `test_every_interval_has_a_period` fails if a new value is added and
#: forgotten here.
INTERVAL_MONTHS: dict[str, int] = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "YEARLY": 12,
    "BIENNIAL": 24,
}


def next_period(start: date, interval: str) -> Period:
    """Roll the billing window forward by one interval."""
    if interval == "WEEKLY":
        # The only cadence that isn't calendar-month arithmetic.
        return Period(start, start + timedelta(days=7))
    months = INTERVAL_MONTHS.get(interval)
    if months is None:
        raise ValueError(f"Unknown interval {interval}")
    return Period(start, _add_months(start, months))


def _add_months(d: date, months: int) -> date:
    """Calendar-month arithmetic that survives month-end.

    Jan 31 + 1 month is Feb 28/29, not an exception and not March 3rd.
    """
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    import calendar

    return calendar.monthrange(year, month)[1]
