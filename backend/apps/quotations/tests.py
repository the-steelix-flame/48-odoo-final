"""Upsell panel tests. Database-backed — pricing resolves against a price list.

The case that matters: a plan an admin created a minute ago has no pairing
rows, and before the recurring tier existed it could never be suggested at all.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Customer, User
from apps.catalog.models import (
    PriceList,
    Product,
    ProductCategory,
    ProductPairing,
    UpsellConfig,
)
from apps.common.enums import LineType, RecurringInterval, Role
from apps.quotations.models import Quotation, QuotationLine
from apps.quotations.upsell import suggestions_for
from apps.subscriptions.models import RecurringPlan


class UpsellSuggestionTests(TestCase):
    def setUp(self):
        UpsellConfig.objects.update_or_create(
            pk=1, defaults={"min_margin_percent": 20, "promoted_boost": Decimal("0.25")}
        )
        self.category = ProductCategory.objects.create(name="Hardware")
        self.price_list = PriceList.objects.create(name="Standard", currency="USD")
        self.customer = Customer.objects.create(name="Acme", currency="USD")
        self.rep = User.objects.create(email="rep@test.local", full_name="R. Ep", role=Role.SALES_REP)

        self.laptop = self._product("Laptop", "LP", 1200, 800)
        self.quotation = Quotation.objects.create(
            number="Q-TEST-1",
            customer=self.customer,
            owner_rep=self.rep,
            price_list=self.price_list,
            currency="USD",
        )
        QuotationLine.objects.create(
            quotation=self.quotation,
            product=self.laptop,
            description=self.laptop.name,
            line_type=LineType.ONE_TIME,
            quantity=1,
            unit_price=Decimal("1200"),
            unit_cost=Decimal("800"),
            line_subtotal=Decimal("1200"),
            line_total=Decimal("1200"),
        )

    def _product(self, name, sku, price, cost, *, plan=None, promoted=False):
        return Product.objects.create(
            name=name,
            sku=sku,
            category=self.category,
            base_price=Decimal(str(price)),
            cost_price=Decimal(str(cost)),
            tax_percent=Decimal("0"),
            is_subscription=plan is not None,
            recurring_plan=plan,
            is_promoted=promoted,
        )

    def _plan(self, name="Care 2yr", interval=RecurringInterval.BIENNIAL, active=True):
        return RecurringPlan.objects.create(name=name, interval=interval, is_active=active)

    # -- the actual ask -------------------------------------------------
    def test_a_brand_new_plan_is_suggested_with_no_pairing_rows(self):
        plan = self._plan()
        self._product("Care Plan 2yr", "SB-CARE2", 500, 100, plan=plan)

        names = [s["product_name"] for s in suggestions_for(self.quotation)]
        self.assertIn("Care Plan 2yr", names)

    def test_the_suggestion_says_which_cadence_it_commits_to(self):
        plan = self._plan()
        self._product("Care Plan 2yr", "SB-CARE2", 500, 100, plan=plan)

        entry = next(
            s for s in suggestions_for(self.quotation) if s["product_name"] == "Care Plan 2yr"
        )
        self.assertEqual(entry["plan_label"], "Every 2 years")

    # -- it must not displace real evidence -----------------------------
    def test_pairings_outrank_recurring_fillers(self):
        paired = self._product("Docking Station", "DOCK", 300, 100)
        ProductPairing.objects.create(
            source_product=self.laptop, target_product=paired, co_purchase_score=Decimal("0.9")
        )
        self._product("Care Plan 2yr", "SB-CARE2", 500, 100, plan=self._plan())

        suggestions = suggestions_for(self.quotation)
        self.assertEqual(suggestions[0]["product_name"], "Docking Station")

    def test_fillers_never_push_the_result_past_the_limit(self):
        for i in range(5):
            self._product(f"Plan {i}", f"PL{i}", 500, 100, plan=self._plan(f"Plan {i}"))

        self.assertLessEqual(len(suggestions_for(self.quotation, limit=3)), 3)

    # -- the same rules still apply -------------------------------------
    def test_a_retired_plan_is_not_suggested(self):
        plan = self._plan("Retired", active=False)
        self._product("Old Care Plan", "SB-OLD", 500, 100, plan=plan)

        names = [s["product_name"] for s in suggestions_for(self.quotation)]
        self.assertNotIn("Old Care Plan", names)

    def test_a_thin_margin_plan_is_floored_out_like_anything_else(self):
        """95% cost against a 20% floor. Recurring is not exempt from the
        rule that a suggestion must not dilute the deal."""
        self._product("Loss Leader Plan", "SB-LOSS", 100, 95, plan=self._plan("Thin"))

        names = [s["product_name"] for s in suggestions_for(self.quotation)]
        self.assertNotIn("Loss Leader Plan", names)

    def test_a_plan_with_no_product_is_invisible_rather_than_unaddable(self):
        """A plan is a billing policy; the product is the thing with a price.
        Offering a plan a rep cannot add to the cart is worse than silence."""
        self._plan("Orphan Plan")

        names = [s["product_name"] for s in suggestions_for(self.quotation)]
        self.assertNotIn("Orphan Plan", names)

    def test_something_already_in_the_cart_is_not_suggested_back(self):
        plan = self._plan()
        care = self._product("Care Plan 2yr", "SB-CARE2", 500, 100, plan=plan)
        QuotationLine.objects.create(
            quotation=self.quotation,
            product=care,
            description=care.name,
            line_type=LineType.RECURRING,
            quantity=1,
            unit_price=Decimal("500"),
            unit_cost=Decimal("100"),
            line_subtotal=Decimal("500"),
            line_total=Decimal("500"),
        )

        names = [s["product_name"] for s in suggestions_for(self.quotation)]
        self.assertNotIn("Care Plan 2yr", names)

    def test_a_full_pairing_cart_still_gets_offered_a_service_plan(self):
        """The reported bug. Three strong pairings filled every slot, so a
        laptop quote was never once prompted to attach a plan."""
        for name, sku, score in [
            ("Docking Station", "DOCK", "0.82"),
            ("Wireless Mouse", "MOUSE", "0.74"),
            ("Extended Warranty", "WARR", "0.55"),
        ]:
            target = self._product(name, sku, 300, 100)
            ProductPairing.objects.create(
                source_product=self.laptop, target_product=target,
                co_purchase_score=Decimal(score),
            )
        self._product("Aftercare Service", "SB-AFTER", 1400, 520, plan=self._plan())

        suggestions = suggestions_for(self.quotation, limit=3)
        self.assertEqual(len(suggestions), 3)
        self.assertEqual(
            [s["product_name"] for s in suggestions if s["plan_label"]],
            ["Aftercare Service"],
        )

    def test_the_reserved_slot_is_released_once_the_cart_has_a_plan(self):
        """Prompt served its purpose — give the space back to correlation."""
        for name, sku, score in [
            ("Docking Station", "DOCK", "0.82"),
            ("Wireless Mouse", "MOUSE", "0.74"),
            ("Extended Warranty", "WARR", "0.55"),
        ]:
            target = self._product(name, sku, 300, 100)
            ProductPairing.objects.create(
                source_product=self.laptop, target_product=target,
                co_purchase_score=Decimal(score),
            )
        care = self._product("Aftercare Service", "SB-AFTER", 1400, 520, plan=self._plan())
        QuotationLine.objects.create(
            quotation=self.quotation, product=care, description=care.name,
            line_type=LineType.RECURRING, quantity=1, unit_price=Decimal("1400"),
            unit_cost=Decimal("520"), line_subtotal=Decimal("1400"), line_total=Decimal("1400"),
        )

        suggestions = suggestions_for(self.quotation, limit=3)
        self.assertEqual(len(suggestions), 3)
        self.assertEqual([s["plan_label"] for s in suggestions], [None, None, None])
