"""Unit tests for the split planner. No database required."""

from decimal import Decimal

from django.test import SimpleTestCase

from apps.fulfillment.planner import Demand, WarehouseStock, plan_split


def wh(wid, name, weight, available, base=Decimal("30")):
    return WarehouseStock(wid, name, Decimal(str(weight)), base, available)


MAIN = 1
EAST = 2


class SplitPlannerTests(SimpleTestCase):
    def test_prefers_a_single_warehouse_even_when_it_is_not_the_cheapest_per_unit(self):
        """Fewer parcels beats marginally cheaper parcels."""
        plan = plan_split(
            demands=[Demand(1, product_id=10, variant_id=None, quantity=5)],
            warehouses=[
                wh(MAIN, "Main Warehouse", 1.0, {(10, None): 5}),
                wh(EAST, "East Depot", 1.4, {(10, None): 50}),
            ],
        )
        self.assertEqual(plan.estimated_shipments, 1)
        self.assertEqual(plan.allocations[0].warehouse_name, "Main Warehouse")
        self.assertTrue(plan.fully_fulfilled)

    def test_splits_across_two_warehouses_when_no_single_one_can_cover(self):
        """The demo case: 24 laptops, Main has 18, East has 6."""
        plan = plan_split(
            demands=[Demand(1, product_id=10, variant_id=None, quantity=24)],
            warehouses=[
                wh(MAIN, "Main Warehouse", 1.0, {(10, None): 18}),
                wh(EAST, "East Depot", 1.4, {(10, None): 6}),
            ],
        )
        self.assertEqual(plan.estimated_shipments, 2)
        self.assertTrue(plan.fully_fulfilled)
        by_name = {a.warehouse_name: a.quantity for a in plan.allocations}
        self.assertEqual(by_name["Main Warehouse"], 18)
        self.assertEqual(by_name["East Depot"], 6)
        # 30×1.0 + 30×1.4
        self.assertEqual(plan.estimated_cost, Decimal("72.00"))

    def test_shortfall_becomes_a_backorder_rather_than_silently_vanishing(self):
        plan = plan_split(
            demands=[Demand(1, product_id=10, variant_id=None, quantity=30)],
            warehouses=[
                wh(MAIN, "Main Warehouse", 1.0, {(10, None): 18}),
                wh(EAST, "East Depot", 1.4, {(10, None): 6}),
            ],
        )
        self.assertFalse(plan.fully_fulfilled)
        backorders = [a for a in plan.allocations if a.is_backorder]
        self.assertEqual(sum(a.quantity for a in backorders), 6)
        self.assertIn("backorder", plan.notes)

    def test_multi_line_order_picks_the_warehouse_covering_the_most_value(self):
        plan = plan_split(
            demands=[
                Demand(1, 10, None, 2, unit_value=Decimal("1200")),
                Demand(2, 20, None, 2, unit_value=Decimal("180")),
            ],
            warehouses=[
                wh(MAIN, "Main Warehouse", 1.0, {(10, None): 2}),  # the laptops
                wh(EAST, "East Depot", 1.4, {(20, None): 2}),  # the docks
            ],
        )
        self.assertEqual(plan.estimated_shipments, 2)
        self.assertTrue(plan.fully_fulfilled)
        first = plan.allocations[0]
        # Highest-value coverage is picked first.
        self.assertEqual(first.warehouse_name, "Main Warehouse")

    def test_no_warehouses_configured_backorders_everything(self):
        plan = plan_split([Demand(1, 10, None, 3)], [])
        self.assertFalse(plan.fully_fulfilled)
        self.assertTrue(all(a.is_backorder for a in plan.allocations))

    def test_order_with_no_physical_lines_is_a_no_op(self):
        plan = plan_split([], [wh(MAIN, "Main Warehouse", 1.0, {})])
        self.assertEqual(plan.estimated_shipments, 0)
        self.assertEqual(plan.allocations, [])
