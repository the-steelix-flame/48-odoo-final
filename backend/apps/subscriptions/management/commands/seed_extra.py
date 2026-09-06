"""Fill out the demo data that `seed_demo` leaves thin.  Owner: anubhaw0raj.

    python manage.py seed_extra

Deliberately a SECOND command rather than edits to `seed_demo`. That one is
sinjeki's and builds the canonical story the demo script walks through; this one
only fills gaps that appear once several people have been clicking around, and
can be re-run without disturbing what is already there.

Everything here goes through the ordinary services — `create_account`,
`create_business`, `confirm` — rather than writing rows directly, so the data it
produces obeys the same rules as data a user creates. Fabricated rows would look
right on screen and behave differently the moment anyone touched them.

Idempotent: every step checks for what it is about to create, so running it
twice is a no-op and running it after someone has been clicking around only
fills what is still missing.

Order matters, and the steps in `handle` are in it: staff before businesses (a
business is assigned to a rep), categories before products (a product needs
one), products before stock (stock is per product), businesses before portal
logins, and all of it before the passwords step, which normalises whatever the
services minted along the way.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Customer, SalesTeam, User
from apps.catalog.models import Product, ProductCategory
from apps.common.enums import CustomerTier, LineType, QuotationStatus, Role
from apps.fulfillment.models import StockItem, Warehouse
from apps.governance.models import CategoryDiscountCeiling
from apps.quotations.models import Quotation
from apps.subscriptions.models import RecurringPlan

#: The password every seeded account ends up with. Documented in CLAUDE.md and
#: shown on the login screen's demo hint, so it cannot be a random string.
DEMO_PASSWORD = "dealflow"

#: (email, full name, role, team name or None)
STAFF = [
    ("rep3@dealflow360.test", "S. Iyer", Role.SALES_REP, "West Team"),
    ("rep4@dealflow360.test", "D. Mehta", Role.SALES_REP, "East Team"),
    ("rep5@dealflow360.test", "A. Fernandes", Role.SALES_REP, "West Team"),
    ("rep6@dealflow360.test", "K. Bose", Role.SALES_REP, "East Team"),
    # A second approver on each rung, so the demo can show that the chain is a
    # role and not a person — either manager can clear a MEDIUM quote.
    ("manager2@dealflow360.test", "R. Kulkarni", Role.SALES_MANAGER, "East Team"),
    ("finance2@dealflow360.test", "T. Menon", Role.FINANCE, None),
]

#: (code, name, discount ceiling %).
#:
#: The ceiling matters as much as the category. `quotations.services` resolves
#: it with `ceilings.get(category_id, tier_ceiling)`, so a category with no row
#: silently inherits the tier's and every line in it looks compliant. It
#: degrades quietly rather than failing, which is worse — the demo would show a
#: discount sailing through with no explanation on screen.
#:
#: SOFTWARE at 8% is stricter than every tier including Gold, so it reproduces
#: the brief's "a Gold customer is still flagged" case on a second category
#: rather than only on Services.
CATEGORIES = [
    ("NETWORKING", "Networking", Decimal("12")),
    ("SOFTWARE", "Software Licences", Decimal("8")),
    ("CONSUMABLES", "Consumables", Decimal("20")),
    ("FURNITURE", "Office Furniture", Decimal("15")),
]

#: (sku, name, category code, base price, tax %, promoted)
#: Tax follows what is already in the catalogue: physical goods 15%, services
#: and licences 10%. Cost price is derived, not listed — see `_products`.
PRODUCTS = [
    ("HW-MON27", "Monitor 27 inch", "HARDWARE", 340, 15, True),
    ("HW-MON32", "Monitor 32 inch 4K", "HARDWARE", 520, 15, False),
    ("HW-LAP16", "Laptop Pro 16", "HARDWARE", 1650, 15, True),
    ("HW-DESK1", "Desktop Tower", "HARDWARE", 980, 15, False),
    ("HW-TAB10", "Tablet 10 inch", "HARDWARE", 430, 15, False),
    ("HW-HEAD", "Wireless Headset", "HARDWARE", 120, 15, False),
    ("HW-WEBC", "Webcam HD", "HARDWARE", 95, 15, False),
    ("HW-SCAN", "Document Scanner", "HARDWARE", 260, 15, False),
    ("HW-UPS", "UPS 1500VA", "HARDWARE", 310, 15, False),
    ("HW-SSD1", "External SSD 1TB", "HARDWARE", 140, 15, False),
    ("NW-RTR", "Edge Router", "NETWORKING", 480, 15, False),
    ("NW-SW24", "24-Port Switch", "NETWORKING", 620, 15, True),
    ("NW-SW48", "48-Port Switch", "NETWORKING", 1150, 15, False),
    ("NW-AP", "Wi-Fi Access Point", "NETWORKING", 210, 15, False),
    ("NW-FW", "Firewall Appliance", "NETWORKING", 1400, 15, False),
    ("NW-CAB", "Cat6 Cable 25m", "NETWORKING", 35, 15, False),
    ("NW-RACK", "Server Rack 12U", "NETWORKING", 540, 15, False),
    ("NW-PATCH", "Patch Panel 24-Port", "NETWORKING", 130, 15, False),
    ("SW-OFFICE", "Office Suite Licence", "SOFTWARE", 220, 10, True),
    ("SW-AV", "Endpoint Security Licence", "SOFTWARE", 95, 10, False),
    ("SW-CAD", "CAD Licence", "SOFTWARE", 1300, 10, False),
    ("SW-ERP", "ERP Module Licence", "SOFTWARE", 2400, 10, False),
    ("SW-BI", "BI Dashboard Licence", "SOFTWARE", 780, 10, False),
    ("SW-VPN", "VPN Client Licence", "SOFTWARE", 60, 10, False),
    ("CN-TONER", "Toner Cartridge", "CONSUMABLES", 85, 15, False),
    ("CN-PAPER", "A4 Paper (Box of 5)", "CONSUMABLES", 42, 15, False),
    ("CN-LABEL", "Label Roll", "CONSUMABLES", 28, 15, False),
    ("CN-CLEAN", "Cleaning Kit", "CONSUMABLES", 22, 15, False),
    ("CN-BATT", "Battery Pack", "CONSUMABLES", 38, 15, False),
    ("CN-CABLE", "USB-C Cable", "CONSUMABLES", 18, 15, False),
    ("FN-DESK", "Office Desk", "FURNITURE", 390, 15, False),
    ("FN-CHAIR", "Ergonomic Chair", "FURNITURE", 310, 15, True),
    ("FN-CAB", "Filing Cabinet", "FURNITURE", 240, 15, False),
    ("FN-SOFA", "Reception Sofa", "FURNITURE", 720, 15, False),
    ("FN-TABLE", "Meeting Table", "FURNITURE", 860, 15, False),
    ("FN-SHELF", "Storage Shelf", "FURNITURE", 180, 15, False),
    ("SV-INSTALL", "Network Installation", "SERVICES", 1200, 10, False),
    ("SV-AUDIT", "Security Audit", "SERVICES", 1600, 10, True),
    ("SV-MIGRATE", "Data Migration", "SERVICES", 2200, 10, False),
    ("SV-CONSULT", "Consulting Day Rate", "SERVICES", 950, 10, False),
    ("SV-SUPPORT", "Priority Support Callout", "SERVICES", 380, 10, False),
    ("SV-DECOM", "Decommissioning Service", "SERVICES", 540, 10, False),
]

#: (name, contact email, tier, address). Tiers are spread on purpose — the
#: ceiling table only tells a story if all three bands are represented in the
#: customer list, and Bronze at 5% is where an ordinary-looking discount starts
#: tripping approvals.
BUSINESSES = [
    ("Helios Manufacturing", "contact@helios.test", CustomerTier.GOLD, "Hinjewadi Phase 2, Pune"),
    ("Vertex Logistics", "contact@vertex.test", CustomerTier.SILVER, "Ambattur, Chennai"),
    ("Quarry Foods", "contact@quarry.test", CustomerTier.BRONZE, "Satpur MIDC, Nashik"),
    ("Lumen Health", "contact@lumen.test", CustomerTier.GOLD, "Gachibowli, Hyderabad"),
    ("Ironwood Furniture", "contact@ironwood.test", CustomerTier.SILVER, "Sitapura, Jaipur"),
    ("Cobalt Analytics", "contact@cobalt.test", CustomerTier.BRONZE, "Whitefield, Bengaluru"),
    ("Summit Education", "contact@summit.test", CustomerTier.SILVER, "Kakkanad, Kochi"),
    ("Harbor Marine", "contact@harbor.test", CustomerTier.GOLD, "Port Road, Kandla"),
]


class Command(BaseCommand):
    help = "Top up the demo data seed_demo leaves thin (staff, catalogue, businesses, stock, subscriptions)."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Topping up demo data...")
        self._staff()
        self._categories()
        self._products()
        self._businesses()
        self._plan_products()
        self._stock_every_product()
        self._portal_logins()
        self._demo_passwords()
        self._subscriptions()
        self._bills()
        self.stdout.write(self.style.SUCCESS("Done."))

    # ------------------------------------------------------------------ staff
    def _staff(self) -> None:
        """More reps, so per-rep numbers mean something.

        Discount-anomaly detection is relative to the rep's own trailing
        average, and the leaderboard ranks reps against each other. With two
        reps in the whole system both are close to meaningless — one outlier
        moves an average built from a handful of quotes, and a leaderboard of
        two is a comparison, not a ranking.
        """
        from apps.accounts import staff

        made = 0
        for email, full_name, role, team_name in STAFF:
            if User.objects.filter(email__iexact=email).exists():
                continue
            team = SalesTeam.objects.filter(name=team_name).first() if team_name else None
            staff.create_account(
                email=email,
                full_name=full_name,
                role=role,
                sales_team_id=team.pk if team else None,
            )
            made += 1
        self.stdout.write(f"  staff accounts created: {made}")

    # ------------------------------------------------------------- categories
    def _categories(self) -> None:
        """New categories, each with the ceiling that makes it visible to risk."""
        made = 0
        for code, name, ceiling in CATEGORIES:
            category, created = ProductCategory.objects.get_or_create(
                code=code, defaults={"name": name}
            )
            made += int(created)
            CategoryDiscountCeiling.objects.get_or_create(
                category=category, defaults={"max_discount_percent": ceiling}
            )
        self.stdout.write(f"  categories created: {made} (each with a discount ceiling)")

    # --------------------------------------------------------------- products
    def _products(self) -> None:
        """A catalogue big enough that search and the upsell panel have work to do.

        `cost_price` is derived rather than listed so that no row can be typed
        with a margin that is accidentally negative. The quotation screen shows
        live margin, and one bad row there reads as a broken calculation rather
        than as bad data.
        """
        by_code = {c.code: c for c in ProductCategory.objects.all()}
        made = 0
        for sku, name, category_code, price, tax, promoted in PRODUCTS:
            category = by_code.get(category_code)
            if category is None:
                continue
            _, created = Product.objects.get_or_create(
                sku=sku,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": "Each",
                    "base_price": Decimal(price),
                    # 58% of list — a ~42% margin, which stays healthy under
                    # every ceiling in the discount table.
                    "cost_price": (Decimal(price) * Decimal("0.58")).quantize(Decimal("0.01")),
                    "tax_percent": Decimal(tax),
                    "is_promoted": promoted,
                    "description": f"{name} ({category.name}).",
                },
            )
            made += int(created)
        self.stdout.write(f"  products created: {made} (catalogue now {Product.objects.count()})")

    # ------------------------------------------------------------- businesses
    def _businesses(self) -> None:
        """Ten-plus businesses, spread across reps and all three tiers.

        Round-robined over every active rep rather than dumped on one, so the
        dashboard's own-pipeline filter, the leaderboard and the per-rep
        discount averages all have more than one populated row.
        """
        from apps.accounts import businesses

        reps = list(User.objects.filter(role=Role.SALES_REP, is_active=True).order_by("pk"))
        made = 0
        for index, (name, email, tier, address) in enumerate(BUSINESSES):
            if Customer.objects.filter(name__iexact=name).exists():
                continue
            # If the address is already taken but the business is not, minting
            # the portal login would raise and abort the whole command. Register
            # the business without one; `_portal_logins` picks it up later if
            # the collision is ever cleared.
            free_email = not User.objects.filter(email__iexact=email).exists()
            businesses.create_business(
                name=name,
                contact_email=email,
                tier=tier,
                address=address,
                owner_rep_id=reps[index % len(reps)].pk if reps else None,
                create_portal_login=free_email,
            )
            made += 1
        self.stdout.write(f"  businesses registered: {made} (total {Customer.objects.count()})")

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
            if User.objects.filter(email__iexact=customer.contact_email).exists():
                # Someone else already owns that address; issuing would raise
                # and take the whole command down with it.
                continue
            businesses.issue_portal_login(customer)
            made.append(customer.contact_email)
        self.stdout.write(f"  portal logins issued: {len(made)}" + (f" ({', '.join(made)})" if made else ""))

    # ------------------------------------------------------------- passwords
    def _demo_passwords(self) -> None:
        """Give every seeded account the documented demo password.

        `create_account` and `issue_portal_login` both MINT A RANDOM PASSWORD
        and return it once — right for a real onboarding, useless for a demo,
        because the string is never written down anywhere. Five of the six
        customer portals were unopenable for exactly this reason: the accounts
        existed, the passwords did not survive the command that made them.

        Scoped to `.test` addresses, which covers the whole seeded set and can
        never be a real one — RFC 2606 reserves `.test` precisely so it cannot
        resolve. On a live deployment there are no such users, so this is a
        no-op there rather than a way to reset somebody's account.
        """
        changed = 0
        for user in User.objects.filter(email__iendswith=".test"):
            if user.check_password(DEMO_PASSWORD):
                continue
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            changed += 1
        self.stdout.write(f"  passwords normalised to '{DEMO_PASSWORD}': {changed}")

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

        fallback_rep = User.objects.filter(role=Role.SALES_REP, is_active=True).first()
        if fallback_rep is None:
            return

        made = 0
        targets = list(Customer.objects.select_related("owner_rep"))
        for index, customer in enumerate(targets):
            # One extra confirmed hybrid order per customer, at most.
            already = customer.quotations.filter(
                status=QuotationStatus.CONFIRMED,
                lines__line_type=LineType.RECURRING,
            ).exists()
            if already:
                continue

            # The account's own rep, not whichever rep sorts first. Booking every
            # seeded order to one person would drag that rep's trailing discount
            # average down toward these 3% lines and leave everyone else with
            # nothing to be measured against.
            rep = customer.owner_rep if customer.owner_rep_id else fallback_rep

            quotation = quotations.create_quotation(customer=customer, owner_rep=rep)
            quotations.add_line(
                quotation,
                product_id=physical[index % len(physical)].pk,
                quantity=Decimal("2"),
                # Under the Bronze ceiling of 5%, so this auto-approves at every
                # tier. A seed that parks its orders in someone's approval queue
                # does not populate the screens it was written to populate.
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

    # ----------------------------------------------------------------- bills
    def _bills(self) -> None:
        """Bill some of the confirmed deals, and pay some of those.

        `confirm()` deliberately does not invoice — confirmation is the customer
        accepting the terms, billing is Finance accepting them, and the brief
        keeps those apart. So a seed that only confirms leaves every new order
        sitting unbilled and the invoice screens exactly as empty as before.

        Deliberately partial, in thirds, because a screen where every row says
        the same thing demonstrates nothing:

          - one third stays CONFIRMED and unbilled, so Finance's Release bill
            button has something real to act on;
          - one third is billed and left OPEN;
          - one third is billed and part-paid, so the invoice list shows
            PARTIALLY_PAID and the amount-due column is not just the total.

        Idempotent through the service itself: `raise_bill_for_quotation`
        refuses a second bill for a deal that already has one, so a re-run
        cannot double-invoice.
        """
        from apps.billing import services as billing
        from apps.common.enums import InvoiceStatus, PaymentMethod
        from apps.common.errors import ValidationError as DomainError

        finance = User.objects.filter(role=Role.FINANCE, is_active=True).first()
        billed = paid = 0

        confirmed = Quotation.objects.filter(status=QuotationStatus.CONFIRMED).order_by("pk")
        for index, quotation in enumerate(confirmed):
            if index % 3 == 0:
                continue  # left for Finance to release by hand
            if billing.deal_invoices(quotation).exists():
                continue
            try:
                invoice = billing.raise_bill_for_quotation(quotation, actor=finance)
            except DomainError:
                # Nothing billable on this one (no one-time lines and no
                # schedule). Not an error worth aborting the whole seed for.
                continue
            billed += 1

            # Part-pay every second billed deal, ~40% of the total.
            if index % 3 == 2 and invoice.status == InvoiceStatus.OPEN and invoice.total > 0:
                billing.record_payment(
                    invoice,
                    amount=(invoice.total * Decimal("0.4")).quantize(Decimal("0.01")),
                    method=PaymentMethod.BANK_TRANSFER,
                    reference=f"SEED-{quotation.number}",
                    actor=finance,
                )
                paid += 1
        self.stdout.write(f"  bills raised: {billed} (part-paid: {paid})")
