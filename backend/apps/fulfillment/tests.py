"""Fulfillment tests.

`SplitPlannerTests` is pure — no database. `ShippingTests` below needs one,
because despatch deducts stock and reads billing state.
"""

from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.accounts import businesses
from apps.accounts.models import User
from apps.billing import services as billing
from apps.billing.api import _lifecycle
from apps.catalog.models import Product, ProductCategory
from apps.common.enums import (
    CustomerTier,
    FulfillmentStatus,
    QuotationStatus,
    Role,
    StockMoveReason,
)
from apps.common.errors import ValidationError
from apps.fulfillment import services as fulfillment
from apps.fulfillment.models import StockItem, StockMove, Warehouse
from apps.fulfillment.planner import Demand, WarehouseStock, plan_split
from apps.governance.models import CategoryDiscountCeiling, TierDiscountCeiling
from apps.negotiation import services as negotiation
from apps.quotations import services as quotations
from apps.quotations.models import Quotation


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


class ShippingTests(TestCase):
    """The tail of the lifecycle: confirmed -> invoiced -> paid -> shipped.

    Owner: the-steelix-flame. Nothing wrote `shipped_at` before `mark_shipped`
    existed, so the Shipped milestone was unreachable — the invoice stepper
    showed it grey forever and orders never left the fulfillment queue.
    """

    def setUp(self):
        self.rep = User.objects.create_user(
            email="rep@ship.test", password="x", full_name="Rep", role=Role.SALES_REP
        )
        self.finance = User.objects.create_user(
            email="fin@ship.test", password="x", full_name="Fin", role=Role.FINANCE
        )
        result = businesses.create_business(
            name="Ship Co", contact_email="buyer@ship.test", tier=CustomerTier.GOLD
        )
        self.customer = result.customer
        self.buyer = result.portal_user

        TierDiscountCeiling.objects.create(
            tier=CustomerTier.GOLD, max_discount_percent=Decimal("15")
        )
        category = ProductCategory.objects.create(name="Hardware", code="HARDWARE")
        CategoryDiscountCeiling.objects.create(
            category=category, max_discount_percent=Decimal("15")
        )
        self.product = Product.objects.create(
            name="Laptop", sku="HW-SHIP", category=category,
            base_price=Decimal("1000"), cost_price=Decimal("600"), tax_percent=Decimal("0"),
        )
        self.warehouse = Warehouse.objects.create(
            name="Main Warehouse", code="MAIN", base_shipment_cost=Decimal("30")
        )
        self.stock = StockItem.objects.create(
            warehouse=self.warehouse, product=self.product, quantity_on_hand=10
        )

    def _confirmed(self):
        quotation = quotations.create_quotation(customer=self.customer, owner_rep=self.rep)
        quotations.add_line(
            quotation, product_id=self.product.id, quantity=Decimal("2"),
            discount_percent=Decimal("5"), actor=self.rep,
        )
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)
        negotiation.confirm_by_customer(quotation, actor=self.buyer)
        quotation.refresh_from_db()
        return quotation

    def _paid_order(self):
        """A confirmed, billed and settled order with an accepted split."""
        quotation = self._confirmed()
        billing.raise_bill_for_quotation(quotation, actor=self.finance)
        negotiation.pay_bill(quotation, actor=self.buyer)

        plan = quotation.fulfillment_plans.first()
        fulfillment.accept_plan(plan, actor=self.finance)
        plan.refresh_from_db()
        return quotation, plan

    def test_an_unpaid_order_is_not_shipped(self):
        """The rule the lifecycle rests on: goods leave after the money arrives.
        Shipping is the one step that cannot be taken back."""
        quotation = self._confirmed()
        plan = quotation.fulfillment_plans.first()
        fulfillment.accept_plan(plan, actor=self.finance)
        plan.refresh_from_db()

        with self.assertRaises(ValidationError):
            fulfillment.mark_shipped(plan, actor=self.finance)

    def test_an_unaccepted_split_cannot_ship(self):
        quotation = self._confirmed()
        plan = quotation.fulfillment_plans.first()

        with self.assertRaises(ValidationError):
            fulfillment.mark_shipped(plan, actor=self.finance)

    def test_shipping_a_paid_order_stamps_every_allocation(self):
        _, plan = self._paid_order()
        fulfillment.mark_shipped(plan, actor=self.finance)
        plan.refresh_from_db()

        self.assertEqual(plan.status, FulfillmentStatus.SHIPPED)
        self.assertFalse(plan.allocations.filter(shipped_at__isnull=True).exists())

    def test_shipping_deducts_stock_and_clears_the_reservation(self):
        """`_reserve` raised `reserved` without touching `on_hand`, because a
        reservation is a promise. Shipping is the movement, so both drop —
        releasing the reservation alone would hand the same units out twice."""
        _, plan = self._paid_order()
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 10)
        self.assertEqual(self.stock.quantity_reserved, 2)

        fulfillment.mark_shipped(plan, actor=self.finance)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 8)
        self.assertEqual(self.stock.quantity_reserved, 0)
        self.assertEqual(self.stock.available, 8)

    def test_shipping_records_a_stock_move(self):
        _, plan = self._paid_order()
        fulfillment.mark_shipped(plan, actor=self.finance)

        move = StockMove.objects.filter(
            stock_item=self.stock, reason=StockMoveReason.SHIP
        ).get()
        self.assertEqual(move.delta, -2)

    def test_shipping_twice_is_refused(self):
        _, plan = self._paid_order()
        fulfillment.mark_shipped(plan, actor=self.finance)
        plan.refresh_from_db()

        with self.assertRaises(ValidationError):
            fulfillment.mark_shipped(plan, actor=self.finance)

    def test_a_shipped_order_leaves_the_fulfillment_queue(self):
        """The reported bug: the queue listed every confirmed order forever, so
        a fully despatched one sat there with nothing left to do."""
        quotation, plan = self._paid_order()

        def queued():
            ids = []
            for q in Quotation.objects.filter(status=QuotationStatus.CONFIRMED):
                p = q.fulfillment_plans.first()
                if p is None or p.status != FulfillmentStatus.SHIPPED:
                    ids.append(q.id)
            return ids

        self.assertIn(quotation.id, queued())
        fulfillment.mark_shipped(plan, actor=self.finance)
        self.assertNotIn(quotation.id, queued())

    def test_the_customer_is_told_once_it_has_actually_been_despatched(self):
        quotation, plan = self._paid_order()
        self.assertIn("being prepared", negotiation.portal_shipping(quotation))

        fulfillment.mark_shipped(plan, actor=self.finance)
        quotation.refresh_from_db()

        after = negotiation.portal_shipping(quotation)
        self.assertIn("despatched", after)
        self.assertIn("Main Warehouse", after)

    def test_the_invoice_lifecycle_runs_confirmed_invoiced_paid_shipped(self):
        """Shipped used to sit second, reading as though goods went out before
        anyone had been billed."""
        quotation, plan = self._paid_order()
        fulfillment.mark_shipped(plan, actor=self.finance)

        stages = _lifecycle(billing.bill_for(quotation))
        self.assertEqual(
            [s["label"] for s in stages],
            ["Order Confirmed", "Invoiced", "Paid", "Shipped"],
        )
        self.assertTrue(all(s["done"] for s in stages))


class StockAdministrationTests(TestCase):
    """Adding a product to a warehouse, and correcting a row by hand.

    Owner: anubhaw0raj. Stock lives per (warehouse, product), so a product with
    no row at a warehouse is invisible to the planner there rather than "zero" —
    which meant the catalogue could grow without any of it becoming shippable
    and the only remedy was the Django admin.
    """

    def setUp(self):
        self.finance = User.objects.create_user(
            email="fin@stock.test", password="x", full_name="Fin", role=Role.FINANCE
        )
        category = ProductCategory.objects.create(name="Hardware", code="HW-STK")
        self.product = Product.objects.create(
            name="Router", sku="HW-RTR-T", category=category,
            base_price=Decimal("100"), cost_price=Decimal("50"), tax_percent=Decimal("0"),
        )
        self.plan = Product.objects.create(
            name="Care Plan", sku="SB-CARE-T", category=category,
            base_price=Decimal("20"), cost_price=Decimal("8"), tax_percent=Decimal("0"),
            is_subscription=True,
        )
        self.warehouse = Warehouse.objects.create(
            name="Depot", code="DEP-T", base_shipment_cost=Decimal("30")
        )

    def test_opening_quantity_lands_in_the_ledger_not_just_the_column(self):
        """`quantity_on_hand` must always equal the sum of its moves.

        That identity is the only reason the ledger can explain a level; writing
        the opening balance straight to the column would break it on row one.
        """
        item = fulfillment.add_stock_item(
            warehouse=self.warehouse, product=self.product, quantity=25, actor=self.finance
        )
        self.assertEqual(item.quantity_on_hand, 25)
        moves = StockMove.objects.filter(stock_item=item)
        self.assertEqual(moves.count(), 1)
        self.assertEqual(moves.first().reason, StockMoveReason.RESTOCK)
        self.assertEqual(sum(m.delta for m in moves), item.quantity_on_hand)

    def test_a_product_can_only_be_stocked_once_per_warehouse(self):
        """Second add must be refused, not silently create a duplicate row —
        availability is summed per row, so two rows would double the stock."""
        fulfillment.add_stock_item(warehouse=self.warehouse, product=self.product, quantity=5)
        with self.assertRaises(ValidationError):
            fulfillment.add_stock_item(warehouse=self.warehouse, product=self.product, quantity=5)

    def test_a_subscription_cannot_hold_stock(self):
        """Subscriptions are billed on a schedule, never boxed."""
        with self.assertRaises(ValidationError):
            fulfillment.add_stock_item(warehouse=self.warehouse, product=self.plan, quantity=1)

    def test_adjusting_on_hand_writes_a_signed_move(self):
        item = fulfillment.add_stock_item(
            warehouse=self.warehouse, product=self.product, quantity=10
        )
        fulfillment.adjust_stock(item, quantity_on_hand=4, actor=self.finance)
        item.refresh_from_db()
        self.assertEqual(item.quantity_on_hand, 4)
        adjust = StockMove.objects.get(stock_item=item, reason=StockMoveReason.ADJUST)
        self.assertEqual(adjust.delta, -6)
        self.assertEqual(
            sum(m.delta for m in StockMove.objects.filter(stock_item=item)),
            item.quantity_on_hand,
        )

    def test_on_hand_cannot_be_cut_below_what_is_reserved(self):
        """Reserved units are promised to accepted plans. Allowing this would
        make `available` negative and let the splitter commit stock twice."""
        item = fulfillment.add_stock_item(
            warehouse=self.warehouse, product=self.product, quantity=10
        )
        item.quantity_reserved = 6
        item.save(update_fields=["quantity_reserved"])
        with self.assertRaises(ValidationError):
            fulfillment.adjust_stock(item, quantity_on_hand=5)
        item.refresh_from_db()
        self.assertEqual(item.quantity_on_hand, 10)

    def test_reorder_fields_change_without_touching_the_ledger(self):
        """A trigger is not a movement — editing it must not invent a move."""
        item = fulfillment.add_stock_item(
            warehouse=self.warehouse, product=self.product, quantity=10
        )
        before = StockMove.objects.filter(stock_item=item).count()
        fulfillment.adjust_stock(item, reorder_point=7, reorder_quantity=30)
        item.refresh_from_db()
        self.assertEqual(item.reorder_point, 7)
        self.assertEqual(item.reorder_quantity, 30)
        self.assertEqual(StockMove.objects.filter(stock_item=item).count(), before)

    def test_a_no_op_adjustment_writes_nothing(self):
        """Saving the form unchanged must not litter the ledger."""
        item = fulfillment.add_stock_item(
            warehouse=self.warehouse, product=self.product, quantity=10
        )
        before = StockMove.objects.filter(stock_item=item).count()
        fulfillment.adjust_stock(item, quantity_on_hand=10)
        self.assertEqual(StockMove.objects.filter(stock_item=item).count(), before)
