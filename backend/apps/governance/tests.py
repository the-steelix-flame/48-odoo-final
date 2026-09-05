"""Unit tests for the risk engine.

`risk.py` is a pure function, so these run without a database:

    python manage.py test apps.governance

These are the two scenarios from the brief, plus the edge cases that would
otherwise be found live, on stage, by a judge.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from apps.governance.risk import LineInput, RiskConfigData, score_quotation


def line(label, subtotal, discount, ceiling, line_id=None):
    return LineInput(
        line_id=line_id,
        label=label,
        line_subtotal=Decimal(str(subtotal)),
        discount_percent=Decimal(str(discount)),
        category_ceiling=Decimal(str(ceiling)),
    )


class BriefScenarioTests(SimpleTestCase):
    """The worked example from section 10 of the problem statement."""

    def test_one_bad_service_line_flags_a_gold_quote(self):
        result = score_quotation(
            lines=[
                line("Laptop Pro 14 (Hardware)", 2400, 12, 15),
                line("Onsite Setup Service (Services)", 450, 18, 10),
                line("Extended Warranty (Hardware)", 180, 10, 15),
            ],
            tier_ceiling=Decimal("15"),
        )

        self.assertTrue(result.requires_approval)
        self.assertEqual(result.band, "MEDIUM")
        self.assertEqual(result.worst_line_excess, Decimal("8.00"))
        self.assertEqual(result.score, Decimal("47.13"))

        # The Hardware line at 12% is fine; the Services line at 18% is not,
        # even though 18% < the 15% Gold tier ceiling would suggest.
        hardware, service, warranty = result.lines
        self.assertFalse(hardware.is_over)
        self.assertTrue(service.is_over)
        self.assertEqual(service.allowed_percent, Decimal("10"))
        self.assertEqual(service.excess_points, Decimal("8.00"))
        self.assertFalse(warranty.is_over)

    def test_many_small_excesses_are_caught_even_though_none_look_alarming(self):
        """Death by a thousand cuts — the reason the score is 'blended'."""
        result = score_quotation(
            lines=[
                line("Line A", 1000, 17, 15),
                line("Line B", 1000, 18, 15),
                line("Line C", 1000, 17, 15),
                line("Line D", 1000, 18, 15),
                line("Line E", 1000, 17, 15),
            ],
            tier_ceiling=Decimal("15"),
        )

        # No single line is dramatic...
        self.assertEqual(result.worst_line_excess, Decimal("3.00"))
        # ...but the pattern across the order is.
        self.assertEqual(result.blended_excess, Decimal("2.40"))
        self.assertEqual(result.order_level_excess, Decimal("2.40"))
        self.assertEqual(result.score, Decimal("39.00"))
        self.assertTrue(result.requires_approval)


class BandRoutingTests(SimpleTestCase):
    def test_fully_compliant_quote_needs_no_approval(self):
        result = score_quotation(
            lines=[line("Laptop", 2400, 10, 15), line("Service", 450, 8, 10)],
            tier_ceiling=Decimal("15"),
        )
        self.assertEqual(result.band, "NONE")
        self.assertFalse(result.requires_approval)
        self.assertEqual(result.score, Decimal("0.00"))
        self.assertIn("within", result.explanation)

    def test_severe_breach_routes_to_finance(self):
        result = score_quotation(
            lines=[line("Service", 5000, 40, 10)],
            tier_ceiling=Decimal("15"),
        )
        self.assertEqual(result.band, "HIGH")  # → Sales Manager then Finance
        self.assertEqual(result.worst_line_excess, Decimal("30.00"))
        self.assertEqual(result.score, Decimal("100.00"))

    def test_order_level_discount_alone_can_trigger_approval(self):
        """Every line is clean, but the order-level discount blows the tier."""
        result = score_quotation(
            lines=[line("Laptop", 1000, 0, 15)],
            tier_ceiling=Decimal("15"),
            order_discount_percent=Decimal("25"),
        )
        self.assertTrue(result.requires_approval)
        self.assertEqual(result.worst_line_excess, Decimal("0.00"))
        self.assertEqual(result.order_level_excess, Decimal("10.00"))
        self.assertIn("order-level", result.explanation)


class EdgeCaseTests(SimpleTestCase):
    def test_empty_quotation_is_not_flagged(self):
        result = score_quotation(lines=[], tier_ceiling=Decimal("15"))
        self.assertEqual(result.band, "NONE")
        self.assertFalse(result.requires_approval)

    def test_zero_value_lines_do_not_divide_by_zero(self):
        result = score_quotation(
            lines=[line("Freebie", 0, 50, 10)],
            tier_ceiling=Decimal("15"),
        )
        self.assertEqual(result.blended_excess, Decimal("0.00"))
        self.assertTrue(result.requires_approval)  # worst is still 40 points over

    def test_bronze_tier_is_stricter_than_the_category_ceiling(self):
        """min(tier, category) — the tier can be the binding constraint too."""
        result = score_quotation(
            lines=[line("Laptop (Hardware)", 1000, 12, 15)],
            tier_ceiling=Decimal("5"),  # Bronze
        )
        self.assertEqual(result.lines[0].allowed_percent, Decimal("5"))
        self.assertEqual(result.worst_line_excess, Decimal("7.00"))

    def test_config_changes_move_the_band_boundary(self):
        """Thresholds are data. Lower the bar, the same quote routes higher."""
        lines = [line("Service", 1000, 13, 10)]  # scores 33.00
        strict = score_quotation(
            lines, Decimal("15"), config=RiskConfigData(high_band_threshold=Decimal("30"))
        )
        lenient = score_quotation(
            lines, Decimal("15"), config=RiskConfigData(high_band_threshold=Decimal("90"))
        )
        self.assertEqual(strict.band, "HIGH")
        self.assertEqual(lenient.band, "MEDIUM")
        self.assertEqual(strict.score, lenient.score)
