"""Seed the demo database.

    python manage.py seed_demo

Idempotent — `get_or_create` throughout, safe to re-run mid-demo when someone
inevitably breaks the data. Sized so that every screen has non-empty state and
the eight-step verification flow in the README works on a clean database.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Customer, SalesTeam, User
from apps.billing.models import Invoice, InvoiceLine
from apps.catalog.models import (
    PriceList,
    PriceListRule,
    Product,
    ProductAttribute,
    ProductAttributeValue,
    ProductCategory,
    ProductPairing,
    UpsellConfig,
)
from apps.common.enums import (
    CustomerTier,
    InvoiceStatus,
    InvoiceType,
    RecurringInterval,
    RiskBand,
    Role,
)
from apps.fulfillment.models import StockItem, Warehouse
from apps.governance.models import (
    ApprovalRule,
    CategoryDiscountCeiling,
    RiskConfig,
    TierDiscountCeiling,
)
from apps.insights.models import DealHealthConfig
from apps.quotations import services as quotation_services
from apps.subscriptions.models import RecurringPlan

PASSWORD = "dealflow"


class Command(BaseCommand):
    help = "Populate the database with DealFlow360 demo data."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding DealFlow360...")
        users = self._users()
        categories = self._categories()
        plans = self._plans()
        products = self._products(categories, plans)
        price_lists = self._price_lists(products, categories)
        customers = self._customers(users, price_lists)
        self._governance(categories)
        warehouses = self._warehouses()
        self._stock(warehouses, products)
        self._pairings(products)
        self._quotations(users, customers, products)
        self._invoices(customers)
        DealHealthConfig.get_solo()
        UpsellConfig.get_solo()
        RiskConfig.get_solo()

        self.stdout.write(self.style.SUCCESS("\nDone. Log in with any of these:"))
        for email, role in [
            ("admin@dealflow360.test", "Admin"),
            ("rep@dealflow360.test", "Sales Rep"),
            ("manager@dealflow360.test", "Sales Manager"),
            ("finance@dealflow360.test", "Finance / Ops"),
            ("buyer@acme.test", "Customer (portal)"),
        ]:
            self.stdout.write(f"  {email:32} / {PASSWORD}   ({role})")

    # -- accounts ---------------------------------------------------------
    def _users(self) -> dict:
        specs = [
            ("admin@dealflow360.test", "A. Admin", Role.ADMIN),
            ("rep@dealflow360.test", "J. Rao", Role.SALES_REP),
            ("rep2@dealflow360.test", "P. Nair", Role.SALES_REP),
            ("manager@dealflow360.test", "M. Shah", Role.SALES_MANAGER),
            ("finance@dealflow360.test", "R. Iyer", Role.FINANCE),
            ("buyer@acme.test", "C. Buyer (Acme)", Role.CUSTOMER),
            ("buyer@beta.test", "D. Buyer (Beta)", Role.CUSTOMER),
        ]
        users = {}
        for email, name, role in specs:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "full_name": name,
                    "role": role,
                    "is_staff": role == Role.ADMIN,
                    "is_superuser": role == Role.ADMIN,
                },
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            users[email] = user

        west, _ = SalesTeam.objects.get_or_create(
            name="West Team", defaults={"manager": users["manager@dealflow360.test"]}
        )
        SalesTeam.objects.get_or_create(name="East Team")
        for key in ("rep@dealflow360.test", "rep2@dealflow360.test"):
            if users[key].sales_team_id is None:
                users[key].sales_team = west
                users[key].save(update_fields=["sales_team"])
        self.stdout.write(f"  users: {len(users)}")
        return users

    # -- catalog ----------------------------------------------------------
    def _categories(self) -> dict:
        data = [("Hardware", "HARDWARE"), ("Services", "SERVICES"), ("Subscription", "SUBSCRIPTION")]
        cats = {}
        for name, code in data:
            cats[code], _ = ProductCategory.objects.get_or_create(code=code, defaults={"name": name})
        return cats

    def _plans(self) -> dict:
        plans = {}
        for name, interval in [
            ("Monthly Plan", RecurringInterval.MONTHLY),
            ("Quarterly Plan", RecurringInterval.QUARTERLY),
            ("Yearly Plan", RecurringInterval.YEARLY),
        ]:
            plans[interval], _ = RecurringPlan.objects.get_or_create(
                name=name,
                defaults={
                    "interval": interval,
                    "proration_mode": "DAILY",
                    "cancellation_policy": "IMMEDIATE",
                    "refund_mode": "PRORATED",
                    "bill_in_advance": True,
                },
            )
        return plans

    def _products(self, cats: dict, plans: dict) -> dict:
        specs = [
            # sku, name, category, price, cost, tax, subscription, plan, promoted
            ("HW-LAP14", "Laptop Pro 14", "HARDWARE", 1200, 820, 15, False, None, False),
            ("HW-DOCK", "Docking Station", "HARDWARE", 180, 110, 15, False, None, True),
            ("HW-MOUSE", "Wireless Mouse", "HARDWARE", 45, 22, 15, False, None, False),
            ("HW-WARR", "Extended Warranty", "HARDWARE", 180, 60, 15, False, None, False),
            ("SV-SETUP", "Onsite Setup Service", "SERVICES", 450, 300, 10, False, None, False),
            ("SV-TRAIN", "Training Workshop", "SERVICES", 800, 500, 10, False, None, False),
            ("SB-CARE2", "Care Plan 2yr", "SUBSCRIPTION", 46, 18, 0, True, RecurringInterval.MONTHLY, True),
            ("SB-SLA", "Support SLA", "SUBSCRIPTION", 300, 140, 0, True, RecurringInterval.QUARTERLY, False),
        ]
        products = {}
        for sku, name, cat, price, cost, tax, is_sub, plan_key, promoted in specs:
            product, _ = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": cats[cat],
                    "base_price": Decimal(price),
                    "cost_price": Decimal(cost),
                    "tax_percent": Decimal(tax),
                    "unit": "Recurring" if is_sub else "Each",
                    "is_subscription": is_sub,
                    "recurring_plan": plans[plan_key] if plan_key else None,
                    "is_promoted": promoted,
                    "description": f"{name} — seeded demo product.",
                },
            )
            products[sku] = product

        # Variants for the laptop, matching screen 17's example.
        laptop = products["HW-LAP14"]
        for attr_name, values in [
            ("Color", [("Blue", 0), ("Black", 0)]),
            ("RAM", [("4GB", 0), ("8GB", 30)]),
            ("Manufacturer", [("Dell", 10), ("HP", 30)]),
        ]:
            attr, _ = ProductAttribute.objects.get_or_create(product=laptop, name=attr_name)
            for value, extra in values:
                ProductAttributeValue.objects.get_or_create(
                    attribute=attr, value=value, defaults={"extra_price": Decimal(extra)}
                )
        self.stdout.write(f"  products: {len(products)} (+ variants on Laptop Pro 14)")
        return products

    def _price_lists(self, products: dict, cats: dict) -> dict:
        bronze, _ = PriceList.objects.get_or_create(
            name="Bronze USD", defaults={"tier": CustomerTier.BRONZE, "currency": "USD"}
        )
        gold, created = PriceList.objects.get_or_create(
            name="Gold USD", defaults={"tier": CustomerTier.GOLD, "currency": "USD"}
        )
        if created:
            # "Price minus 10 percent base" — screen 17's Gold rule.
            PriceListRule.objects.create(
                price_list=gold,
                rule_type=PriceListRule.RuleType.PERCENT_OFF,
                value=Decimal("10"),
                priority=1,
            )
        return {"BRONZE": bronze, "GOLD": gold}

    def _customers(self, users: dict, price_lists: dict) -> dict:
        rep = users["rep@dealflow360.test"]
        rep2 = users["rep2@dealflow360.test"]
        specs = [
            ("Acme Corp", CustomerTier.GOLD, rep, "buyer@acme.test"),
            ("Beta Industries", CustomerTier.SILVER, rep, "buyer@beta.test"),
            ("Nova Retail", CustomerTier.GOLD, rep2, None),
            ("Zenith Co", CustomerTier.BRONZE, rep2, None),
            ("Delta LLC", CustomerTier.SILVER, rep, None),
            ("Orion Ltd", CustomerTier.GOLD, rep2, None),
        ]
        customers = {}
        for name, tier, owner, portal_email in specs:
            customer, _ = Customer.objects.get_or_create(
                name=name,
                defaults={
                    "tier": tier,
                    "currency": "USD",
                    "contact_email": portal_email or f"contact@{name.split()[0].lower()}.test",
                    "owner_rep": owner,
                    "portal_user": users.get(portal_email) if portal_email else None,
                    "default_price_list": price_lists["GOLD"]
                    if tier == CustomerTier.GOLD
                    else price_lists["BRONZE"],
                },
            )
            customers[name] = customer
        self.stdout.write(f"  customers: {len(customers)}")
        return customers

    # -- governance -------------------------------------------------------
    def _governance(self, cats: dict) -> None:
        for tier, pct in [
            (CustomerTier.BRONZE, 5),
            (CustomerTier.SILVER, 10),
            (CustomerTier.GOLD, 15),
        ]:
            TierDiscountCeiling.objects.get_or_create(
                tier=tier, defaults={"max_discount_percent": Decimal(pct)}
            )
        for code, pct in [("HARDWARE", 15), ("SERVICES", 10), ("SUBSCRIPTION", 10)]:
            CategoryDiscountCeiling.objects.get_or_create(
                category=cats[code], defaults={"max_discount_percent": Decimal(pct)}
            )
        # Screen 18's bottom panel, as data.
        for name, band, lo, hi, roles, seq in [
            ("Within tier / category limit", RiskBand.NONE, 0, 0, [], 1),
            ("Over limit, blended risk medium", RiskBand.MEDIUM, 0, 60, ["SALES_MANAGER"], 2),
            ("Over limit, blended high risk", RiskBand.HIGH, 60, 100,
             ["SALES_MANAGER", "FINANCE"], 3),
        ]:
            ApprovalRule.objects.get_or_create(
                band=band,
                defaults={
                    "name": name,
                    "min_score": Decimal(lo),
                    "max_score": Decimal(hi),
                    "required_roles": roles,
                    "sequence": seq,
                },
            )
        self.stdout.write("  governance: 3 tier ceilings, 3 category ceilings, 3 approval rules")

    # -- fulfillment ------------------------------------------------------
    def _warehouses(self) -> dict:
        main, _ = Warehouse.objects.get_or_create(
            code="MAIN",
            defaults={
                "name": "Main Warehouse",
                "shipping_cost_weight": Decimal("1.0"),
                "base_shipment_cost": Decimal("42"),
            },
        )
        east, _ = Warehouse.objects.get_or_create(
            code="EAST",
            defaults={
                "name": "East Depot",
                "shipping_cost_weight": Decimal("1.4"),
                "base_shipment_cost": Decimal("29"),
            },
        )
        return {"MAIN": main, "EAST": east}

    def _stock(self, warehouses: dict, products: dict) -> None:
        # Tuned so a 24-unit laptop order MUST split across both warehouses.
        specs = [
            ("MAIN", "HW-LAP14", 40, 18),
            ("EAST", "HW-LAP14", 10, 6),
            ("MAIN", "HW-DOCK", 65, 12),
            ("EAST", "HW-DOCK", 20, 0),
            ("MAIN", "HW-MOUSE", 120, 5),
            ("MAIN", "HW-WARR", 500, 0),
            ("MAIN", "SV-SETUP", 999, 0),
            ("MAIN", "SV-TRAIN", 999, 0),
        ]
        for wh_code, sku, on_hand, reserved in specs:
            StockItem.objects.get_or_create(
                warehouse=warehouses[wh_code],
                product=products[sku],
                variant=None,
                defaults={
                    "quantity_on_hand": on_hand,
                    "quantity_reserved": reserved,
                    "reorder_point": 5,
                    "reorder_quantity": 25,
                },
            )
        self.stdout.write("  warehouses: 2, stock rows: 8 (Laptop split forced: 22 + 4 available)")

    def _pairings(self, products: dict) -> None:
        pairs = [
            ("HW-LAP14", "HW-DOCK", "0.82"),
            ("HW-LAP14", "HW-MOUSE", "0.74"),
            ("HW-LAP14", "SB-CARE2", "0.68"),
            ("HW-LAP14", "HW-WARR", "0.55"),
            ("HW-DOCK", "HW-MOUSE", "0.61"),
            ("SV-SETUP", "SV-TRAIN", "0.58"),
            ("SV-SETUP", "SB-SLA", "0.52"),
        ]
        for source, target, score in pairs:
            ProductPairing.objects.get_or_create(
                source_product=products[source],
                target_product=products[target],
                defaults={"co_purchase_score": Decimal(score)},
            )

    # -- quotations -------------------------------------------------------
    def _quotations(self, users: dict, customers: dict, products: dict) -> None:
        if quotation_services.Quotation.objects.exists():
            self.stdout.write("  quotations: already seeded, skipping")
            return

        rep = users["rep@dealflow360.test"]
        rep2 = users["rep2@dealflow360.test"]

        # 1. Acme — the brief's own example. One Services line 8 points over.
        acme = quotation_services.create_quotation(customer=customers["Acme Corp"], owner_rep=rep)
        quotation_services.add_line(
            acme, product_id=products["HW-LAP14"].id, quantity=Decimal("2"),
            discount_percent=Decimal("12"), actor=rep,
        )
        quotation_services.add_line(
            acme, product_id=products["SV-SETUP"].id, quantity=Decimal("1"),
            discount_percent=Decimal("18"), actor=rep,
        )
        quotation_services.add_line(
            acme, product_id=products["HW-WARR"].id, quantity=Decimal("1"),
            discount_percent=Decimal("10"), actor=rep,
        )

        # 2. Beta — pending approval, mixed one-time + recurring.
        beta = quotation_services.create_quotation(
            customer=customers["Beta Industries"], owner_rep=rep
        )
        quotation_services.add_line(
            beta, product_id=products["HW-LAP14"].id, quantity=Decimal("12"),
            discount_percent=Decimal("14"), actor=rep,
        )
        quotation_services.add_line(
            beta, product_id=products["SB-SLA"].id, quantity=Decimal("1"),
            discount_percent=Decimal("5"), actor=rep,
        )
        quotation_services.submit(beta, actor=rep)

        # 3. Nova — clean quote, auto-approved with no human in the loop.
        nova = quotation_services.create_quotation(
            customer=customers["Nova Retail"], owner_rep=rep2
        )
        quotation_services.add_line(
            nova, product_id=products["HW-DOCK"].id, quantity=Decimal("20"),
            discount_percent=Decimal("8"), actor=rep2,
        )
        quotation_services.submit(nova, actor=rep2)

        # 4. Zenith — idle 9 days, so the stalled alert fires immediately.
        zenith = quotation_services.create_quotation(
            customer=customers["Zenith Co"], owner_rep=rep2
        )
        quotation_services.add_line(
            zenith, product_id=products["HW-MOUSE"].id, quantity=Decimal("40"),
            discount_percent=Decimal("4"), actor=rep2,
        )
        stale = timezone.now() - timedelta(days=9)
        quotation_services.Quotation.objects.filter(pk=zenith.pk).update(last_activity_at=stale)

        # 5. Delta — 22% against a rep who averages ~8%: the anomaly case.
        delta = quotation_services.create_quotation(
            customer=customers["Delta LLC"], owner_rep=rep
        )
        quotation_services.add_line(
            delta, product_id=products["SV-TRAIN"].id, quantity=Decimal("4"),
            discount_percent=Decimal("22"), actor=rep,
        )

        self.stdout.write("  quotations: 5 across the pipeline (1 stalled, 1 discount anomaly)")

    def _invoices(self, customers: dict) -> None:
        if Invoice.objects.exists():
            return
        today = timezone.now().date()
        invoice = Invoice.objects.create(
            number="INV-1038",
            customer=customers["Nova Retail"],
            invoice_type=InvoiceType.ONE_TIME,
            status=InvoiceStatus.PAID,
            issue_date=today - timedelta(days=20),
            due_date=today - timedelta(days=5),
            subtotal=Decimal("9750"),
            total=Decimal("9750"),
            amount_paid=Decimal("9750"),
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description="Docking Station × 20",
            quantity=Decimal("20"),
            unit_price=Decimal("487.50"),
            line_total=Decimal("9750"),
        )
        self.stdout.write("  invoices: 1 historical paid invoice")
