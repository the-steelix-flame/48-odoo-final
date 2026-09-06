"""Business onboarding tests.  Owner: the-steelix-flame.

    python manage.py test apps.accounts

These need a database (they create real users and hash real passwords), so
they're TestCase rather than SimpleTestCase.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts import businesses, warehouses
from apps.accounts.models import Customer, User
from apps.fulfillment.models import Warehouse
from apps.common.enums import CustomerTier, Role
from apps.common.errors import ValidationError


class PasswordGenerationTests(TestCase):
    def test_password_avoids_ambiguous_characters(self):
        """These get read aloud and retyped off a screenshot."""
        for _ in range(50):
            password = businesses.generate_password()
            self.assertEqual(len(password), businesses.PASSWORD_LENGTH)
            for char in "lIO01":
                self.assertNotIn(char, password)

    def test_passwords_are_not_repeated(self):
        generated = {businesses.generate_password() for _ in range(200)}
        self.assertEqual(len(generated), 200)


class CreateBusinessTests(TestCase):
    def test_creates_customer_and_portal_login(self):
        result = businesses.create_business(
            name="Northwind Traders",
            contact_email="buyer@northwind.test",
            tier=CustomerTier.GOLD,
        )

        self.assertEqual(result.customer.name, "Northwind Traders")
        self.assertEqual(result.customer.tier, CustomerTier.GOLD)
        self.assertIsNotNone(result.portal_user)
        self.assertEqual(result.portal_user.role, Role.CUSTOMER)
        self.assertEqual(result.customer.portal_user_id, result.portal_user.id)

        # The password works, and is stored hashed rather than in the clear.
        self.assertTrue(result.portal_user.check_password(result.password))
        self.assertNotEqual(result.portal_user.password, result.password)

    def test_password_is_never_recoverable_after_creation(self):
        """The whole security posture of this feature in one assertion."""
        result = businesses.create_business(
            name="Contoso", contact_email="buyer@contoso.test"
        )
        reloaded = User.objects.get(pk=result.portal_user.id)
        self.assertNotIn(result.password, reloaded.password)
        # Nothing on the customer row carries it either.
        for value in Customer.objects.filter(pk=result.customer.id).values()[0].values():
            self.assertNotEqual(value, result.password)

    def test_business_can_be_registered_without_a_login(self):
        result = businesses.create_business(
            name="Fabrikam", contact_email="", create_portal_login=False
        )
        self.assertIsNone(result.portal_user)
        self.assertIsNone(result.password)
        self.assertIsNone(result.customer.portal_user_id)

    def test_duplicate_business_name_is_rejected(self):
        businesses.create_business(name="Acme Inc", contact_email="a@acme.test")
        with self.assertRaises(ValidationError):
            businesses.create_business(name="acme inc", contact_email="b@acme.test")

    def test_email_already_in_use_is_rejected(self):
        """Guards against silently hijacking an existing staff account."""
        User.objects.create_user(
            email="taken@example.test", password="x", role=Role.SALES_REP
        )
        with self.assertRaises(ValidationError):
            businesses.create_business(name="Globex", contact_email="taken@example.test")

    def test_login_requires_an_email(self):
        with self.assertRaises(ValidationError):
            businesses.create_business(name="Initech", contact_email="")

    def test_unknown_tier_is_rejected(self):
        with self.assertRaises(ValidationError):
            businesses.create_business(
                name="Umbrella", contact_email="u@umbrella.test", tier="PLATINUM"
            )


class ResetAndAccessTests(TestCase):
    def setUp(self):
        self.result = businesses.create_business(
            name="Stark Industries", contact_email="buyer@stark.test"
        )
        self.customer = self.result.customer

    def test_reset_issues_a_working_new_password_and_kills_the_old_one(self):
        old = self.result.password
        reset = businesses.reset_portal_password(self.customer)

        self.assertNotEqual(reset.password, old)
        user = User.objects.get(pk=self.result.portal_user.id)
        self.assertTrue(user.check_password(reset.password))
        self.assertFalse(user.check_password(old))

    def test_reset_reactivates_a_suspended_login(self):
        """Reset is how you recover an account, so it must un-suspend too."""
        businesses.set_portal_access(self.customer, enabled=False)
        businesses.reset_portal_password(self.customer)
        self.assertTrue(User.objects.get(pk=self.result.portal_user.id).is_active)

    def test_suspending_access_preserves_the_account(self):
        businesses.set_portal_access(self.customer, enabled=False)
        user = User.objects.get(pk=self.result.portal_user.id)
        self.assertFalse(user.is_active)
        # Still linked — revoking access must not rewrite negotiation history.
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.portal_user_id, user.id)

    def test_access_can_be_restored(self):
        businesses.set_portal_access(self.customer, enabled=False)
        businesses.set_portal_access(self.customer, enabled=True)
        self.assertTrue(User.objects.get(pk=self.result.portal_user.id).is_active)

    def test_reset_without_a_login_is_rejected(self):
        bare = businesses.create_business(
            name="No Login Co", contact_email="", create_portal_login=False
        ).customer
        with self.assertRaises(ValidationError):
            businesses.reset_portal_password(bare)

    def test_issuing_a_login_to_a_business_that_has_one_is_rejected(self):
        with self.assertRaises(ValidationError):
            businesses.issue_portal_login(self.customer)

    def test_issue_login_backfills_a_business_registered_without_one(self):
        bare = businesses.create_business(
            name="Later Co", contact_email="", create_portal_login=False
        ).customer
        bare.contact_email = "buyer@later.test"
        bare.save()

        issued = businesses.issue_portal_login(bare)
        self.assertIsNotNone(issued.password)
        self.assertTrue(issued.portal_user.check_password(issued.password))
        bare.refresh_from_db()
        self.assertEqual(bare.portal_user_id, issued.portal_user.id)


class StaffProvisioningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="root@dealflow.test", password="x", full_name="Root", role=Role.ADMIN
        )

    def test_creates_an_internal_account_with_a_working_password(self):
        from apps.accounts import staff

        result = staff.create_account(
            email="New.Rep@dealflow.test", full_name="New Rep", role=Role.SALES_REP
        )
        self.assertEqual(result.user.email, "new.rep@dealflow.test")  # normalised
        self.assertEqual(result.user.role, Role.SALES_REP)
        self.assertTrue(result.user.check_password(result.password))
        self.assertFalse(result.user.is_staff)

    def test_admin_accounts_get_django_admin_access(self):
        from apps.accounts import staff

        result = staff.create_account(
            email="admin2@dealflow.test", full_name="Second Admin", role=Role.ADMIN
        )
        self.assertTrue(result.user.is_staff)
        self.assertTrue(result.user.is_superuser)

    def test_customer_role_is_refused_here(self):
        """A CUSTOMER user without a Customer row can log in and then hit a
        wall on every portal route. Refuse, and point at the right door."""
        from apps.accounts import staff

        with self.assertRaises(ValidationError) as ctx:
            staff.create_account(
                email="buyer@x.test", full_name="Buyer", role=Role.CUSTOMER
            )
        self.assertIn("Business Management", str(ctx.exception))

    def test_duplicate_email_is_refused(self):
        from apps.accounts import staff

        staff.create_account(email="dup@x.test", full_name="A", role=Role.SALES_REP)
        with self.assertRaises(ValidationError):
            staff.create_account(email="DUP@x.test", full_name="B", role=Role.FINANCE)

    def test_name_and_email_are_required(self):
        from apps.accounts import staff

        with self.assertRaises(ValidationError):
            staff.create_account(email="", full_name="A", role=Role.SALES_REP)
        with self.assertRaises(ValidationError):
            staff.create_account(email="a@x.test", full_name="  ", role=Role.SALES_REP)

    def test_reset_reactivates_and_replaces_the_password(self):
        from apps.accounts import staff

        created = staff.create_account(
            email="rep9@x.test", full_name="Rep Nine", role=Role.SALES_REP
        )
        staff.set_access(created.user, enabled=False)
        reset = staff.reset_password(created.user)

        user = User.objects.get(pk=created.user.pk)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(reset.password))
        self.assertFalse(user.check_password(created.password))

    def test_cannot_deactivate_yourself(self):
        from apps.accounts import staff

        other = staff.create_account(
            email="admin3@x.test", full_name="Third", role=Role.ADMIN
        ).user
        self.assertTrue(other.is_active)  # a second admin exists, so it's not the last-admin guard
        with self.assertRaises(ValidationError) as ctx:
            staff.set_access(self.admin, enabled=False, actor=self.admin)
        self.assertIn("your own account", str(ctx.exception))

    def test_a_second_admin_can_be_deactivated_while_one_remains(self):
        """The last-admin guard must not block ordinary offboarding."""
        from apps.accounts import staff

        second = staff.create_account(
            email="admin4@x.test", full_name="Fourth", role=Role.ADMIN
        ).user
        staff.set_access(second, enabled=False, actor=self.admin)
        second.refresh_from_db()
        self.assertFalse(second.is_active)

    def test_last_admin_cannot_be_demoted_or_disabled(self):
        from apps.accounts import staff

        rep = staff.create_account(
            email="rep10@x.test", full_name="Rep Ten", role=Role.SALES_REP
        ).user
        # self.admin is the only admin.
        with self.assertRaises(ValidationError) as ctx:
            staff.set_access(self.admin, enabled=False, actor=rep)
        self.assertIn("last active admin", str(ctx.exception))

        with self.assertRaises(ValidationError):
            staff.change_role(self.admin, role=Role.SALES_REP, actor=rep)

    def test_role_change_updates_django_admin_flags(self):
        from apps.accounts import staff

        rep = staff.create_account(
            email="rep11@x.test", full_name="Rep Eleven", role=Role.SALES_REP
        ).user
        staff.change_role(rep, role=Role.ADMIN)
        rep.refresh_from_db()
        self.assertTrue(rep.is_staff)

        staff.change_role(rep, role=Role.FINANCE)
        rep.refresh_from_db()
        self.assertFalse(rep.is_staff)


class ChangeOwnPasswordTests(TestCase):
    """Distinct from an admin reset: here the current password IS the proof."""

    def setUp(self):
        from apps.accounts import staff

        self.result = staff.create_account(
            email="self@x.test", full_name="Self Serve", role=Role.SALES_REP
        )
        self.user = self.result.user

    def test_changing_with_the_right_current_password_works(self):
        from apps.accounts import staff

        staff.change_own_password(
            self.user, current_password=self.result.password, new_password="brand-new-pass"
        )
        reloaded = User.objects.get(pk=self.user.pk)
        self.assertTrue(reloaded.check_password("brand-new-pass"))
        self.assertFalse(reloaded.check_password(self.result.password))

    def test_a_wrong_current_password_is_refused(self):
        """Otherwise anyone at an unlocked screen could lock the owner out."""
        from apps.accounts import staff

        with self.assertRaises(ValidationError) as ctx:
            staff.change_own_password(
                self.user, current_password="not-it", new_password="brand-new-pass"
            )
        self.assertIn("not correct", str(ctx.exception))
        self.assertTrue(
            User.objects.get(pk=self.user.pk).check_password(self.result.password)
        )

    def test_too_short_is_refused(self):
        from apps.accounts import staff

        with self.assertRaises(ValidationError):
            staff.change_own_password(
                self.user, current_password=self.result.password, new_password="short"
            )

    def test_reusing_the_same_password_is_refused(self):
        from apps.accounts import staff

        with self.assertRaises(ValidationError):
            staff.change_own_password(
                self.user,
                current_password=self.result.password,
                new_password=self.result.password,
            )

    def test_the_new_password_actually_authenticates(self):
        from django.contrib.auth import authenticate

        from apps.accounts import staff

        staff.change_own_password(
            self.user, current_password=self.result.password, new_password="brand-new-pass"
        )
        self.assertIsNotNone(authenticate(username="self@x.test", password="brand-new-pass"))
        self.assertIsNone(authenticate(username="self@x.test", password=self.result.password))


class UserAnalyticsTests(TestCase):
    def test_analytics_are_role_appropriate(self):
        from apps.accounts import analytics, staff

        rep = staff.create_account(
            email="anarep@x.test", full_name="Ana Rep", role=Role.SALES_REP
        ).user
        finance = staff.create_account(
            email="anafin@x.test", full_name="Ana Fin", role=Role.FINANCE
        ).user

        rep_titles = [s["title"] for s in analytics.user_analytics(rep)["sections"]]
        fin_titles = [s["title"] for s in analytics.user_analytics(finance)["sections"]]

        self.assertIn("Selling", rep_titles)
        self.assertNotIn("Approvals", rep_titles)
        self.assertIn("Approvals", fin_titles)
        self.assertNotIn("Selling", fin_titles)

    def test_analytics_on_a_brand_new_user_do_not_divide_by_zero(self):
        """A user with no activity is the most common case on day one."""
        from apps.accounts import analytics, staff

        rep = staff.create_account(
            email="fresh@x.test", full_name="Fresh", role=Role.SALES_REP
        ).user
        data = analytics.user_analytics(rep)
        metrics = {m["label"]: m["value"] for m in data["sections"][0]["metrics"]}
        self.assertEqual(metrics["Quotations created"], "0")
        self.assertEqual(metrics["Win rate"], "—")
        self.assertEqual(data["recent_quotations"], [])

    def test_every_metric_value_is_a_string(self):
        """Regression: `MetricOut.value` is typed `str` and pydantic v2 refuses
        to coerce ints, so a raw count anywhere here is a 500 on the detail
        page. Assert the contract instead of trusting each call site."""
        from apps.accounts import analytics, staff

        for role in (Role.SALES_REP, Role.SALES_MANAGER, Role.FINANCE, Role.ADMIN):
            user = staff.create_account(
                email=f"metric-{role.lower()}@x.test", full_name=f"M {role}", role=role
            ).user
            for section in analytics.user_analytics(user)["sections"]:
                for metric in section["metrics"]:
                    self.assertIsInstance(
                        metric["value"],
                        str,
                        f"{role} / {metric['label']} returned {type(metric['value'])}",
                    )

    def test_customer_without_a_business_is_reported_not_silently_empty(self):
        from apps.accounts import analytics

        orphan = User.objects.create_user(
            email="orphan@x.test", password="x", role=Role.CUSTOMER
        )
        sections = analytics.user_analytics(orphan)["sections"]
        self.assertEqual(sections[0]["metrics"][0]["value"], "Not linked")


class SuspendedLoginTests(TestCase):
    def test_a_suspended_business_cannot_authenticate(self):
        """`authenticate()` refuses inactive users — verify, don't assume."""
        from django.contrib.auth import authenticate

        result = businesses.create_business(
            name="Wayne Enterprises", contact_email="buyer@wayne.test"
        )
        self.assertIsNotNone(
            authenticate(username="buyer@wayne.test", password=result.password)
        )

        businesses.set_portal_access(result.customer, enabled=False)
        self.assertIsNone(
            authenticate(username="buyer@wayne.test", password=result.password)
        )


class WarehouseAdminTests(TestCase):
    """Phase 1 of PLAN-distance-fulfillment.md.

    Nothing here asserts a distance — nothing computes one yet. These cover the
    field scaffolding and the guards that stop an admin breaking allocation.
    """

    def _make(self, **overrides):
        payload = {"name": "Main Warehouse", "code": "WH-MAIN"}
        payload.update(overrides)
        return warehouses.create_warehouse(**payload)

    def test_a_warehouse_can_be_created_with_an_address_and_a_point(self):
        warehouse = self._make(
            address="12 Dock Road, Kolkata", latitude="22.5726", longitude="88.3639"
        )
        self.assertEqual(warehouse.address, "12 Dock Road, Kolkata")
        self.assertEqual(warehouse.latitude, Decimal("22.572600"))
        self.assertEqual(warehouse.longitude, Decimal("88.363900"))
        # Typed by a human, not resolved from the address.
        self.assertIsNone(warehouse.geocoded_at)

    def test_coordinates_are_optional(self):
        """Every row that predates this feature has none, and allocation still
        has to work for them."""
        warehouse = self._make(address="No coordinates yet")
        self.assertIsNone(warehouse.latitude)
        self.assertIsNone(warehouse.longitude)

    def test_half_a_coordinate_pair_is_refused(self):
        """A latitude with no longitude would read as the prime meridian — a
        confidently wrong position, worse than no position."""
        with self.assertRaises(ValidationError):
            self._make(latitude="22.5726")
        with self.assertRaises(ValidationError):
            self._make(longitude="88.3639")

    def test_out_of_range_coordinates_are_refused(self):
        with self.assertRaises(ValidationError):
            self._make(latitude="120", longitude="10")
        with self.assertRaises(ValidationError):
            self._make(latitude="10", longitude="200")

    def test_codes_are_upper_cased_and_unique_case_insensitively(self):
        self._make(code="wh-main")
        self.assertEqual(Warehouse.objects.get().code, "WH-MAIN")
        with self.assertRaises(ValidationError):
            self._make(name="Another", code="Wh-Main")

    def test_names_are_unique_case_insensitively(self):
        self._make()
        with self.assertRaises(ValidationError):
            self._make(name="main warehouse", code="WH-2")

    def test_a_zero_cost_weight_is_refused(self):
        """The splitter sorts on it and multiplies by it — zero makes every
        warehouse look free and identical."""
        with self.assertRaises(ValidationError):
            self._make(shipping_cost_weight="0")
        with self.assertRaises(ValidationError):
            self._make(shipping_cost_weight="-1")

    def test_negative_lead_time_and_cost_are_refused(self):
        with self.assertRaises(ValidationError):
            self._make(base_shipment_cost="-5")
        with self.assertRaises(ValidationError):
            self._make(lead_time_days=-1)

    def test_editing_only_touches_the_keys_it_was_given(self):
        warehouse = self._make(address="Old address", lead_time_days=5)
        warehouses.update_warehouse(warehouse, address="New address")
        warehouse.refresh_from_db()
        self.assertEqual(warehouse.address, "New address")
        self.assertEqual(warehouse.lead_time_days, 5)

    def test_editing_one_coordinate_validates_it_against_the_stored_other(self):
        warehouse = self._make(latitude="22.5726", longitude="88.3639")
        warehouses.update_warehouse(warehouse, latitude="19.0760")
        warehouse.refresh_from_db()
        self.assertEqual(warehouse.latitude, Decimal("19.076000"))
        self.assertEqual(warehouse.longitude, Decimal("88.363900"))

    def test_the_last_active_warehouse_cannot_be_retired(self):
        """`plan_split` backorders every line when no warehouse is active, so
        this would break all future allocation from one click."""
        warehouse = self._make()
        with self.assertRaises(ValidationError):
            warehouses.set_active(warehouse, enabled=False)

    def test_retiring_is_allowed_once_a_second_warehouse_exists(self):
        first = self._make()
        self._make(name="Depot B", code="WH-B")
        warehouses.set_active(first, enabled=False)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        # Retiring never deletes — stock rows and shipped allocations point here.
        self.assertEqual(Warehouse.objects.count(), 2)

    def test_retired_warehouses_are_still_listed(self):
        """An admin who cannot see a retired warehouse cannot restore it."""
        first = self._make()
        self._make(name="Depot B", code="WH-B")
        warehouses.set_active(first, enabled=False)
        self.assertEqual(warehouses.queryset().count(), 2)


class BusinessAddressTests(TestCase):
    def test_a_business_can_be_onboarded_with_a_delivery_address(self):
        result = businesses.create_business(
            name="Northwind Traders",
            contact_email="buyer@northwind.test",
            address="44 Harbour Street, Mumbai",
            latitude="19.0760",
            longitude="72.8777",
        )
        self.assertEqual(result.customer.address, "44 Harbour Street, Mumbai")
        self.assertEqual(result.customer.latitude, Decimal("19.076000"))

    def test_the_address_is_optional(self):
        result = businesses.create_business(name="Acme", contact_email="b@acme.test")
        self.assertEqual(result.customer.address, "")
        self.assertIsNone(result.customer.latitude)

    def test_half_a_coordinate_pair_is_refused_before_the_login_is_minted(self):
        """Validation runs first, so a bad point cannot leave a portal user
        behind with no customer row."""
        with self.assertRaises(ValidationError):
            businesses.create_business(
                name="Broken Co", contact_email="b@broken.test", latitude="19.0760"
            )
        self.assertFalse(User.objects.filter(email="b@broken.test").exists())
