"""Deal health severity rules.  Owner: anubhaw0raj.

The two pure helpers need no database, so they are tested as pure functions —
which is the point of keeping them pure.
"""

from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.common.enums import AlertSeverity, RiskBand
from apps.insights.health import _at_least, _risk_floor


def _quotation(band: str) -> SimpleNamespace:
    """`_risk_floor` reads one field, so a stand-in is honest here."""
    return SimpleNamespace(risk_band=band)


class SeverityOrderingTests(SimpleTestCase):
    def test_the_stronger_of_the_two_wins_from_either_side(self):
        self.assertEqual(_at_least(AlertSeverity.LOW, AlertSeverity.HIGH), AlertSeverity.HIGH)
        self.assertEqual(_at_least(AlertSeverity.HIGH, AlertSeverity.LOW), AlertSeverity.HIGH)

    def test_a_floor_below_the_ratio_never_weakens_it(self):
        """The floor raises severity; it must never talk one down."""
        self.assertEqual(_at_least(AlertSeverity.HIGH, AlertSeverity.MEDIUM), AlertSeverity.HIGH)
        self.assertEqual(_at_least(AlertSeverity.MEDIUM, AlertSeverity.LOW), AlertSeverity.MEDIUM)

    def test_equal_severities_are_unchanged(self):
        self.assertEqual(_at_least(AlertSeverity.MEDIUM, AlertSeverity.MEDIUM), AlertSeverity.MEDIUM)


class RiskFloorTests(SimpleTestCase):
    def test_each_band_maps_to_its_matching_severity(self):
        self.assertEqual(_risk_floor(_quotation(RiskBand.HIGH)), AlertSeverity.HIGH)
        self.assertEqual(_risk_floor(_quotation(RiskBand.MEDIUM)), AlertSeverity.MEDIUM)
        self.assertEqual(_risk_floor(_quotation(RiskBand.NONE)), AlertSeverity.LOW)

    def test_an_unscored_quotation_floors_at_low_rather_than_raising(self):
        """A blank band must not crash the sweep, and must not invent severity."""
        self.assertEqual(_risk_floor(_quotation("")), AlertSeverity.LOW)


class Q1041RegressionTests(SimpleTestCase):
    """The bug the dashboard actually showed on 2026-09-06.

    Q-1041 discounted 35% against a 12% rep average — 2.9x, a hair under the
    HIGH cut — so the anomaly read MEDIUM while the quotation header read
    RISK 100.00 HIGH. Two screens, one deal, two different verdicts.
    """

    MULTIPLIER = Decimal("2")

    def _by_ratio(self, effective: Decimal, average: Decimal) -> str:
        return (
            AlertSeverity.HIGH
            if effective > average * self.MULTIPLIER * Decimal("1.5")
            else AlertSeverity.MEDIUM
        )

    def test_the_ratio_alone_still_calls_q1041_medium(self):
        """Guards the diagnosis: the ratio is not what was wrong."""
        self.assertEqual(self._by_ratio(Decimal("35"), Decimal("12")), AlertSeverity.MEDIUM)

    def test_the_risk_band_lifts_it_to_high(self):
        severity = _at_least(
            self._by_ratio(Decimal("35"), Decimal("12")),
            _risk_floor(_quotation(RiskBand.HIGH)),
        )
        self.assertEqual(severity, AlertSeverity.HIGH)

    def test_a_wild_ratio_on_a_low_risk_deal_is_still_high(self):
        """The floor adds severity; the ratio must keep its own voice."""
        severity = _at_least(
            self._by_ratio(Decimal("40"), Decimal("5")),
            _risk_floor(_quotation(RiskBand.NONE)),
        )
        self.assertEqual(severity, AlertSeverity.HIGH)
