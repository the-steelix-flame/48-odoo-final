"""Customer portal tests.  Owner: the-steelix-flame.

    python manage.py test apps.negotiation

Covers the two bugs found while wiring the portal list, plus the isolation
guarantees the brief requires of a "real, separate, restricted view".
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounts import businesses
from apps.accounts.models import User
from apps.catalog.models import Product, ProductCategory
from apps.common.enums import CustomerTier, QuotationStatus, Role
from apps.common.errors import NotFound, PermissionDenied, ValidationError
from apps.governance.models import CategoryDiscountCeiling, TierDiscountCeiling
from apps.negotiation import services as negotiation
from apps.quotations import services as quotations


class PortalTestBase(TestCase):
    def setUp(self):
        self.rep = User.objects.create_user(
            email="rep@t.test", password="x", full_name="Rep", role=Role.SALES_REP
        )
        result = businesses.create_business(
            name="Portal Co", contact_email="buyer@portal.test", tier=CustomerTier.GOLD
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
            name="Laptop", sku="HW-1", category=category,
            base_price=Decimal("1000"), cost_price=Decimal("600"), tax_percent=Decimal("0"),
        )

    def _quotation(self, discount="5"):
        quotation = quotations.create_quotation(customer=self.customer, owner_rep=self.rep)
        quotations.add_line(
            quotation, product_id=self.product.id, quantity=Decimal("1"),
            discount_percent=Decimal(discount), actor=self.rep,
        )
        return quotation


class PortalListingTests(PortalTestBase):
    """Regression: the portal had no index, so a customer could log in and had
    no way to reach anything they'd been sent."""

    def test_unsent_quotations_are_invisible(self):
        self._quotation()
        self.assertEqual(negotiation.portal_quotations_for(self.buyer), [])

    def test_a_sent_quotation_appears(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        rows = negotiation.portal_quotations_for(self.buyer)
        self.assertEqual([q.id for q in rows], [quotation.id])
        self.assertIsNotNone(rows[0].sent_at)

    def test_resending_does_not_duplicate_the_row(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)
        quotation.refresh_from_db()
        quotation.status = QuotationStatus.APPROVED  # allow a second send
        quotation.save(update_fields=["status"])
        negotiation.send_to_customer(quotation, actor=self.rep)

        self.assertEqual(len(negotiation.portal_quotations_for(self.buyer)), 1)

    def test_another_customers_quotation_is_not_listed(self):
        other = businesses.create_business(
            name="Other Co", contact_email="buyer@other.test"
        ).customer
        quotation = quotations.create_quotation(customer=other, owner_rep=self.rep)
        quotations.add_line(
            quotation, product_id=self.product.id, quantity=Decimal("1"), actor=self.rep
        )
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        self.assertEqual(negotiation.portal_quotations_for(self.buyer), [])

    def test_a_login_with_no_business_is_refused(self):
        orphan = User.objects.create_user(
            email="orphan@t.test", password="x", role=Role.CUSTOMER
        )
        with self.assertRaises(PermissionDenied):
            negotiation.portal_quotations_for(orphan)

    def test_status_labels_never_leak_internal_wording(self):
        """A customer shouldn't have to interpret 'Pending Approval'."""
        label, action = negotiation.portal_status(QuotationStatus.PENDING_APPROVAL)
        self.assertEqual(label, "Under internal review")
        self.assertFalse(action)

        label, action = negotiation.portal_status(QuotationStatus.SENT)
        self.assertTrue(action)  # the ball is in the customer's court

        label, action = negotiation.portal_status(QuotationStatus.APPROVED)
        self.assertTrue(action)


class PortalConfirmTests(PortalTestBase):
    def test_customer_can_confirm_a_sent_quotation(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        negotiation.confirm_by_customer(quotation, actor=self.buyer)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.CONFIRMED)

    def test_customer_can_confirm_after_a_counter_offer_is_re_approved(self):
        """Regression: this dead-ended at the final click.

        The brief's loop is counter -> rep accepts -> re-approval -> confirm.
        That last step lands on APPROVED, which the confirm guard rejected —
        while the portal was already telling the customer it was ready.
        """
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.accept_request(request, actor=self.rep)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.PENDING_APPROVAL)

        # Approvers clear it.
        quotation.status = QuotationStatus.APPROVED
        quotation.save(update_fields=["status"])

        label, action_required = negotiation.portal_status(quotation.status)
        self.assertTrue(action_required, "portal says the customer must act…")

        negotiation.confirm_by_customer(quotation, actor=self.buyer)  # …so it must work
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.CONFIRMED)

    def test_cannot_confirm_while_still_under_review(self):
        quotation = self._quotation(discount="40")  # breaches the ceiling
        quotations.submit(quotation, actor=self.rep)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.PENDING_APPROVAL)

        with self.assertRaises(ValidationError):
            negotiation.confirm_by_customer(quotation, actor=self.buyer)


class NegotiationThreadTests(PortalTestBase):
    """Both sides must read the SAME conversation, in order."""

    def _sent(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)
        return quotation

    def test_timeline_interleaves_messages_and_offers_chronologically(self):
        quotation = self._sent()
        negotiation.submit_request(
            quotation, actor=self.buyer,
            requested_discount_percent=Decimal("25"), message="Can you do 25%?",
        )
        negotiation.post_message(
            quotation, actor=self.rep, body="Let me check with my manager.", author_type="REP"
        )

        timeline = negotiation.negotiation_timeline(quotation)
        kinds = [entry["kind"] for entry in timeline]
        self.assertIn("COUNTER_REQUEST", kinds)
        self.assertIn("MESSAGE", kinds)
        # Chronological, so the story reads top to bottom.
        stamps = [entry["created_at"] for entry in timeline]
        self.assertEqual(stamps, sorted(stamps))

    def test_rep_counter_does_not_change_the_quotation_yet(self):
        """A counter is an offer, not a decision. Quoting the customer a total
        that reflects a discount they haven't accepted would be lying."""
        quotation = self._sent()
        before = quotation.total
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12"),
            note="12% is the best we can do.",
        )

        quotation.refresh_from_db()
        self.assertEqual(quotation.total, before)
        request.refresh_from_db()
        self.assertEqual(request.status, "COUNTERED")
        self.assertEqual(request.counter_discount_percent, Decimal("12.00"))

    def test_customer_accepting_our_counter_applies_our_number(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        negotiation.accept_counter(request, actor=self.buyer)

        quotation.refresh_from_db()
        # Our 12%, not their 25%.
        self.assertEqual(quotation.lines.first().discount_percent, Decimal("12.00"))
        request.refresh_from_db()
        self.assertEqual(request.status, "ACCEPTED")

    def test_accepting_our_counter_still_triggers_re_approval(self):
        """The re-approval tail must not depend on WHO agreed."""
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("40")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("30")  # still over 15%
        )
        negotiation.accept_counter(request, actor=self.buyer)

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.PENDING_APPROVAL)

    def test_countering_an_already_answered_request_is_refused(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        with self.assertRaises(ValidationError):
            negotiation.counter_request(
                request, actor=self.rep, counter_discount_percent=Decimal("10")
            )

    def test_accepting_a_counter_that_was_never_made_is_refused(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        with self.assertRaises(ValidationError):
            negotiation.accept_counter(request, actor=self.buyer)

    def test_out_of_range_counter_is_refused(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        with self.assertRaises(ValidationError):
            negotiation.counter_request(
                request, actor=self.rep, counter_discount_percent=Decimal("140")
            )

    def test_empty_message_is_refused(self):
        quotation = self._sent()
        with self.assertRaises(ValidationError):
            negotiation.post_message(
                quotation, actor=self.rep, body="   ", author_type="REP"
            )

    def test_open_request_tracks_whose_turn_it_is(self):
        quotation = self._sent()
        self.assertIsNone(negotiation.open_request_for(quotation))

        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        self.assertEqual(negotiation.open_request_for(quotation).id, request.id)

        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        still_open = negotiation.open_request_for(quotation)
        self.assertEqual(still_open.id, request.id)  # now waiting on the customer

        negotiation.accept_counter(request, actor=self.buyer)
        self.assertIsNone(negotiation.open_request_for(quotation))


class PortalIsolationTests(PortalTestBase):
    def test_access_needs_a_token_not_just_a_login(self):
        quotation = self._quotation()  # never sent, so no token
        with self.assertRaises(NotFound):
            negotiation.authorise_portal_access(self.buyer, quotation.id)

    def test_missing_access_is_not_found_rather_than_forbidden(self):
        """Whether someone else's quotation exists isn't theirs to learn."""
        other = businesses.create_business(
            name="Third Co", contact_email="buyer@third.test"
        ).customer
        quotation = quotations.create_quotation(customer=other, owner_rep=self.rep)
        quotations.add_line(
            quotation, product_id=self.product.id, quantity=Decimal("1"), actor=self.rep
        )
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        with self.assertRaises(NotFound):
            negotiation.authorise_portal_access(self.buyer, quotation.id)
