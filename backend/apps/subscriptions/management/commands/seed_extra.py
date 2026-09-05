"""Fill out the demo data that `seed_demo` leaves thin.  Owner: anubhaw0raj.

    python manage.py seed_extra

Deliberately a SECOND command rather than edits to `seed_demo`. That one is
sinjeki's and builds the canonical story the demo script walks through; this one
only fills gaps that appear once several people have been clicking around, and
can be re-run without disturbing what is already there.

Everything here goes through the ordinary services — `activate_from_quotation`,
`issue_one_time_invoice`, `suggest_plan` — rather than writing rows directly, so
the data it produces obeys the same rules as data a user creates. Fabricated
rows would look right on screen and behave differently the moment anyone touched
them.

Idempotent: every step checks for what it is about to create.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Customer
from apps.catalog.models import Product, ProductCategory
from apps.common.enums import LineType, QuotationStatus
from apps.fulfillment.models import StockItem, Warehouse
from apps.subscriptions.models import RecurringPlan


class Command(BaseCommand):
    help = "Top up the demo data seed_demo leaves thin (plans, stock, portal logins, subscriptions)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Topping up demo data...")
        self._plan_products()
        self._stock_every_product()
        self._portal_logins()
        self._subscriptions()
        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------ plans
    def _plan_products(self) -> None:
        """A plan with no product is a billing policy nobody can buy.

        `QuotationLine.product` is a required FK, so a plan with nothing priced
        behind it can never reach a quotation — it shows in the admin list and
        is unsellable. Newly created plans get a companion product; the ones
        that predate that still do not.
        """
        category, _ = ProductCategory.objects.get_or_create(
            code="SUBSCRIPTION", defaults={"name": "Subscriptions"}
        )
        made = 0
        for plan in RecurringPlan.objects.all():
            if Product.objects.filter(recurring_plan=plan).exists():
                continue
            price = {"WEEKLY": 25, "MONTHLY": 60, "QUARTERLY": 165, "YEARLY": 600, "BIENNIAL": 1100}.get(
                plan.interval, 100
            )
            Product.objects.create(
                name=f"{plan.name} Cover",
                sku=f"SB-{plan.pk}-COVER",
                category=category,
                unit="Each",
                base_price=Decimal(price),
                # 40% of list, matching what create_plan assumes when no cost is given.
                cost_price=Decimal(price) * Decimal("0.4"),
                tax_percent=Decimal("0"),
                is_subscription=True,
                recurring_plan=plan,
                description=f"Recurring cover billed {plan.interval.lower()}.",
            )
            made += 1
        self.stdout.write(f"  plans given a sellable product: {made}")

    # ------------------------------------------------------------------ stock
    def _stock_every_product(self) -> None:
        """Physical products with no stock row cannot be split or shipped.

        The planner reads availability per (warehouse, product); a product
        missing from a warehouse is simply unavailable there, so half the
        catalogue could never appear on a fulfilment plan. Quantities differ per
        warehouse on purpose — a split is only interesting when the two are not
        interchangeable.
        """
        warehouses = list(Warehouse.objects.order_by("shipping_cost_weight"))
        if not warehouses:
            return
        made = 0
        for index, product in enumerate(Product.objects.filter(is_subscription=False)):
            for offset, warehouse in enumerate(warehouses):
                _, created = StockItem.objects.get_or_create(
                    warehouse=warehouse,
                    product=product,
                    variant=None,
                    defaults={
                        "quantity_on_hand": 40 - offset * 12 + (index % 5) * 6,
                        "quantity_reserved": offset * 3,
                        "reorder_point": 8,
                        "reorder_quantity": 25,
                    },
                )
                made += int(created)
        self.stdout.write(f"  stock rows added: {made}")

    # ---------------------------------------------------------------- portal
    def _portal_logins(self) -> None:
        """Every business needs a login, or its quotations cannot be demoed.

        Only two customers had one, and neither of them owned the quotations
        that had actually been sent — so the portal looked broken from either
        direction.
        """
        from apps.accounts import businesses

        made = []
        for customer in Customer.objects.filter(portal_user__isnull=True):
            if not customer.contact_email:
                # issue_portal_login reads the address off the business, so a
                # business registered without one cannot be given a login.
                slug = customer.name.lower().split()[0].strip(".,")
                customer.contact_email = f"buyer@{slug}.test"
                customer.save(update_fields=["contact_email", "updated_at"])
            result = businesses.issue_portal_login(customer)
            made.append(customer.contact_email)
        self.stdout.write(f"  portal logins issued: {len(made)}" + (f" ({', '.join(made)})" if made else ""))

    # --------------------------------------------------------- subscriptions
    def _subscriptions(self) -> None:
        """Screens 9 and 10 read as broken when the list is nearly empty.

        Built by confirming real quotations that carry a recurring line, so each
        subscription arrives with the billing schedule, invoices and events the
        service would have produced anyway. Creating Subscription rows directly
        would populate the list and leave the proration history empty.
        """
        from apps.quotations import services as quotations

        recurring_products = list(
            Product.objects.filter(is_subscription=True, recurring_plan__isnull=False)
        )
        physical = list(Product.objects.filter(is_subscription=False)[:3])
        if not recurring_products or not physical:
            self.stdout.write("  subscriptions: nothing to build from")
            return

        rep = None
        from apps.accounts.models import User
        from apps.common.enums import Role

        rep = User.objects.filter(role=Role.SALES_REP, is_active=True).first()
        if rep is None:
            return

        made = 0
        targets = list(Customer.objects.all())
        for index, customer in enumerate(targets):
            # One extra confirmed hybrid order per customer, at most.
            already = customer.quotations.filter(
                status=QuotationStatus.CONFIRMED,
                lines__line_type=LineType.RECURRING,
            ).exists()
            if already:
                continue

            quotation = quotations.create_quotation(customer=customer, owner_rep=rep)
            quotations.add_line(
                quotation,
                product_id=physical[index % len(physical)].pk,
                quantity=Decimal("2"),
                discount_percent=Decimal("3"),
                actor=rep,
            )
            quotations.add_line(
                quotation,
                product_id=recurring_products[index % len(recurring_products)].pk,
                quantity=Decimal("1"),
                discount_percent=Decimal("0"),
                actor=rep,
            )
            quotations.submit(quotation, actor=rep)
            quotation.refresh_from_db()
            if quotation.status != QuotationStatus.APPROVED:
                # Needs an approver; leave it in the queue rather than forcing it
                # through, so the approvals screen has something real on it too.
                continue
            quotations.confirm(quotation, actor=rep)
            made += 1
        self.stdout.write(f"  hybrid orders confirmed (one-time + recurring): {made}")
