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

    def test_every_move_survives_in_order_including_a_superseded_offer(self):
        """The regression this event log exists for.

        The timeline used to be derived from each request's CURRENT status, so
        accepting our counter overwrote the "we offered 12%" moment with
        "accepted" and it vanished. Both moves must remain, in order.
        """
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer,
            requested_discount_percent=Decimal("25"), message="Can you do 25%?",
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12"),
            note="12% is our best.",
        )
        negotiation.accept_counter(request, actor=self.buyer)

        timeline = negotiation.negotiation_timeline(quotation)
        kinds = [entry["kind"] for entry in timeline]

        self.assertEqual(
            kinds, ["SENT", "COUNTER_REQUEST", "REP_COUNTER", "ACCEPTED"],
            "every move must survive, in the order it happened",
        )

        asked, offered, agreed = timeline[1], timeline[2], timeline[3]
        self.assertEqual(asked["discount_percent"], Decimal("25.00"))
        self.assertEqual(asked["author_type"], "CUSTOMER")
        self.assertEqual(offered["discount_percent"], Decimal("12.00"))
        self.assertEqual(offered["author_type"], "REP")
        self.assertEqual(agreed["discount_percent"], Decimal("12.00"))
        self.assertEqual(agreed["author_type"], "CUSTOMER")

        stamps = [entry["created_at"] for entry in timeline]
        self.assertEqual(stamps, sorted(stamps))

    def test_customers_are_named_as_their_company_not_the_portal_login(self):
        quotation = self._sent()
        negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("20")
        )
        entry = [
            e for e in negotiation.negotiation_timeline(quotation)
            if e["kind"] == "COUNTER_REQUEST"
        ][0]
        self.assertEqual(entry["author_name"], "Portal Co")
        # The login is named "Portal Co (portal)" — the thread must show the
        # company, not the account.
        self.assertNotEqual(entry["author_name"], self.buyer.full_name)

    def test_the_log_is_never_rewritten_by_later_moves(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        before = len(negotiation.negotiation_timeline(quotation))
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        after = negotiation.negotiation_timeline(quotation)
        # Strictly appended — the earlier entries are untouched.
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[1]["discount_percent"], Decimal("25.00"))

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
        before = quotation.lines.first().discount_percent
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        negotiation.accept_counter(request, actor=self.buyer)

        quotation.refresh_from_db()
        # Our 12%, not their 25% — and as an ORDER discount, exactly as when the
        # rep accepts the customer's ask. The per-line figures are untouched.
        self.assertEqual(quotation.order_discount_percent, Decimal("12.00"))
        self.assertEqual(quotation.lines.first().discount_percent, before)
        request.refresh_from_db()
        self.assertEqual(request.status, "ACCEPTED")

    def test_accepting_our_counter_never_cuts_a_deeper_line(self):
        """Regression: `accept_counter` used to loop `update_line` and stamp the
        counter onto every line.

        A line already sitting at 18% was silently CUT to a 12% counter — the
        customer's own haggling made their price worse — and flattening the
        spread changed the blended score the deal is governed by. The rep-accepts
        path had been fixed for exactly this; the customer-accepts path had not,
        so the two disagreed about what a negotiated discount even means.
        """
        quotation = self._quotation(discount="18")
        quotations.submit(quotation, actor=self.rep)
        quotation.refresh_from_db()
        if quotation.status != QuotationStatus.APPROVED:
            quotations.transition(quotation, QuotationStatus.APPROVED, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)

        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        negotiation.accept_counter(request, actor=self.buyer)

        quotation.refresh_from_db()
        self.assertEqual(quotation.lines.first().discount_percent, Decimal("18.00"))
        self.assertEqual(quotation.order_discount_percent, Decimal("12.00"))

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


class NegotiationRoundTests(PortalTestBase):
    """One round at a time, and UNDER_NEGOTIATION means a round is open.

    The board reads the quotation's status; the rep's inbox reads open requests.
    Nothing tied the two together, so they drifted: the sidebar counted a
    request awaiting a reply on a quotation the board filed under Approved, and
    the Negotiation column sat empty while the badge said one.
    """

    def _sent(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)
        return quotation

    def test_a_second_request_cannot_be_stacked_on_an_unanswered_one(self):
        quotation = self._sent()
        negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        with self.assertRaises(ValidationError):
            negotiation.submit_request(
                quotation, actor=self.buyer, requested_discount_percent=Decimal("20")
            )

    def test_a_second_request_cannot_be_stacked_on_our_open_counter(self):
        """A COUNTERED round is still open — it is the customer's move, and
        their move is accept, not 'ask again and orphan the offer'."""
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        with self.assertRaises(ValidationError):
            negotiation.submit_request(
                quotation, actor=self.buyer, requested_discount_percent=Decimal("20")
            )

    def test_submitting_a_request_puts_the_quote_under_negotiation(self):
        quotation = self._sent()
        negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("10")
        )
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.UNDER_NEGOTIATION)

    def test_declining_settles_the_quote_out_of_negotiation(self):
        """A decline ends the round. The quote used to stay UNDER_NEGOTIATION
        afterwards — parked in the board's Negotiation column with nothing left
        to negotiate and no request to act on."""
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.reject_request(request, actor=self.rep, note="Below our floor")

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.APPROVED)
        self.assertIsNone(negotiation.open_request_for(quotation))

    def test_accepting_within_the_ceilings_settles_to_approved(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("5")
        )
        negotiation.accept_request(request, actor=self.rep)

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.APPROVED)
        self.assertIsNone(negotiation.open_request_for(quotation))

    def test_accepting_over_a_ceiling_goes_to_approval_not_approved(self):
        """The settle step must never short-circuit re-approval."""
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("40")
        )
        negotiation.accept_request(request, actor=self.rep)

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.PENDING_APPROVAL)

    def test_under_negotiation_always_means_an_open_round(self):
        """The invariant itself, walked end to end. Every screen that places a
        quotation by status and counts work by open request depends on it."""
        quotation = self._sent()
        self.assertIsNone(negotiation.open_request_for(quotation))

        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("10")
        )
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.UNDER_NEGOTIATION)
        self.assertIsNotNone(negotiation.open_request_for(quotation))

        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("8")
        )
        quotation.refresh_from_db()
        # Still open — it is the customer's move now, not nobody's.
        self.assertEqual(quotation.status, QuotationStatus.UNDER_NEGOTIATION)
        self.assertIsNotNone(negotiation.open_request_for(quotation))

        negotiation.accept_counter(request, actor=self.buyer)
        quotation.refresh_from_db()
        self.assertIsNone(negotiation.open_request_for(quotation))
        self.assertNotEqual(quotation.status, QuotationStatus.UNDER_NEGOTIATION)


class CustomerRejectionTests(PortalTestBase):
    """Walking away is the customer's decision, and only theirs."""

    def _sent(self):
        quotation = self._quotation()
        quotations.submit(quotation, actor=self.rep)
        negotiation.send_to_customer(quotation, actor=self.rep)
        return quotation

    def test_customer_can_decline_a_sent_quotation(self):
        quotation = self._sent()
        negotiation.reject_by_customer(
            quotation, actor=self.buyer, note="Went with another supplier."
        )
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.REJECTED)

    def test_declining_closes_the_round_still_in_flight(self):
        """Otherwise the rep's panel keeps asking for a reply to a dead deal."""
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.reject_by_customer(quotation, actor=self.buyer)

        request.refresh_from_db()
        self.assertEqual(request.status, "REJECTED")
        self.assertIsNone(negotiation.open_request_for(quotation))

    def test_declining_can_happen_mid_negotiation(self):
        quotation = self._sent()
        request = negotiation.submit_request(
            quotation, actor=self.buyer, requested_discount_percent=Decimal("25")
        )
        negotiation.counter_request(
            request, actor=self.rep, counter_discount_percent=Decimal("12")
        )
        quotation.refresh_from_db()

        negotiation.reject_by_customer(quotation, actor=self.buyer, note="Still too high.")
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, QuotationStatus.REJECTED)

    def test_the_rejection_is_on_the_timeline_for_both_sides(self):
        quotation = self._sent()
        negotiation.reject_by_customer(quotation, actor=self.buyer, note="Too expensive.")

        last = negotiation.negotiation_timeline(quotation)[-1]
        self.assertEqual(last["kind"], "REJECTED")
        self.assertEqual(last["author_type"], "CUSTOMER")
        self.assertEqual(last["author_name"], "Portal Co")
        self.assertIn("Too expensive", last["body"])

    def test_a_confirmed_quotation_cannot_then_be_declined(self):
        quotation = self._sent()
        negotiation.confirm_by_customer(quotation, actor=self.buyer)
        quotation.refresh_from_db()

        with self.assertRaises(ValidationError):
            negotiation.reject_by_customer(quotation, actor=self.buyer)

    def test_declined_reads_as_declined_to_the_customer(self):
        label, action_required = negotiation.portal_status(QuotationStatus.REJECTED)
        self.assertEqual(label, "Declined")
        self.assertFalse(action_required)


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
