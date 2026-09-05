"""Unit tests for proration. No database required."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.subscriptions.proration import (
    Period,
    cancellation_refund,
    next_period,
    plan_change,
    quantity_change,
)

SEP = Period(date(2026, 9, 1), date(2026, 10, 1))  # 30 days


class QuantityChangeTests(SimpleTestCase):
    def test_upgrade_midcycle_charges_the_unused_fraction(self):
        """The worked example from WORKFLOW.md §6."""
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 9, 16),
            unit_price=Decimal("46"),
            old_quantity=Decimal("1"),
            new_quantity=Decimal("3"),
        )
        self.assertEqual(result.remaining_days, 15)
        self.assertEqual(result.amount, Decimal("46.00"))
        self.assertTrue(result.is_charge)

    def test_downgrade_is_the_exact_mirror_of_the_upgrade(self):
        """Same formula, opposite sign — upgrades and downgrades can't disagree."""
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 9, 16),
            unit_price=Decimal("46"),
            old_quantity=Decimal("3"),
            new_quantity=Decimal("1"),
        )
        self.assertEqual(result.amount, Decimal("-46.00"))
        self.assertTrue(result.is_credit)

    def test_change_on_the_first_day_charges_the_whole_period(self):
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 9, 1),
            unit_price=Decimal("46"),
            old_quantity=Decimal("0"),
            new_quantity=Decimal("1"),
        )
        self.assertEqual(result.amount, Decimal("46.00"))

    def test_change_on_the_last_day_charges_nothing(self):
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 10, 1),
            unit_price=Decimal("46"),
            old_quantity=Decimal("1"),
            new_quantity=Decimal("5"),
        )
        self.assertEqual(result.amount, Decimal("0.00"))

    def test_proration_mode_none_defers_the_change_to_next_period(self):
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 9, 16),
            unit_price=Decimal("46"),
            old_quantity=Decimal("1"),
            new_quantity=Decimal("3"),
            proration_mode="NONE",
        )
        self.assertEqual(result.amount, Decimal("0.00"))

    def test_proration_mode_full_period_ignores_elapsed_days(self):
        result = quantity_change(
            period=SEP,
            effective_date=date(2026, 9, 16),
            unit_price=Decimal("46"),
            old_quantity=Decimal("1"),
            new_quantity=Decimal("3"),
            proration_mode="FULL_PERIOD",
        )
        self.assertEqual(result.amount, Decimal("92.00"))


class CancellationTests(SimpleTestCase):
    def test_prorated_refund_credits_the_unused_remainder(self):
        result = cancellation_refund(
            period=SEP,
            effective_date=date(2026, 9, 16),
            period_amount=Decimal("138"),  # 3 × 46
        )
        self.assertEqual(result.amount, Decimal("-69.00"))
        self.assertTrue(result.is_credit)

    def test_no_refund_policy_returns_zero(self):
        result = cancellation_refund(
            period=SEP,
            effective_date=date(2026, 9, 16),
            period_amount=Decimal("138"),
            refund_mode="NONE",
        )
        self.assertEqual(result.amount, Decimal("0"))


class PlanChangeTests(SimpleTestCase):
    def test_upgrade_nets_credit_against_charge(self):
        result = plan_change(
            period=SEP,
            effective_date=date(2026, 9, 16),
            old_period_amount=Decimal("46"),
            new_period_amount=Decimal("300"),
        )
        # (300 − 46) × 0.5
        self.assertEqual(result.amount, Decimal("127.00"))


class PeriodArithmeticTests(SimpleTestCase):
    def test_monthly_rollover(self):
        self.assertEqual(next_period(date(2026, 9, 1), "MONTHLY").end, date(2026, 10, 1))

    def test_month_end_does_not_overflow(self):
        """Jan 31 + 1 month is Feb 28, not March 3rd and not a crash."""
        self.assertEqual(next_period(date(2026, 1, 31), "MONTHLY").end, date(2026, 2, 28))

    def test_leap_year_month_end(self):
        self.assertEqual(next_period(date(2028, 1, 31), "MONTHLY").end, date(2028, 2, 29))

    def test_quarterly_and_yearly(self):
        self.assertEqual(next_period(date(2026, 9, 1), "QUARTERLY").end, date(2026, 12, 1))
        self.assertEqual(next_period(date(2026, 9, 1), "YEARLY").end, date(2027, 9, 1))
