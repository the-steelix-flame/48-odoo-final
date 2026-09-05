"""Customer portal negotiation.  Owner: the-steelix-flame."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.enums import (
    NegotiationRequestStatus,
    QuotationEventType,
    QuotationStatus,
)
from apps.common.errors import NotFound, PermissionDenied, ValidationError
from apps.negotiation.models import (
    NegotiationEvent,
    NegotiationMessage,
    NegotiationRequest,
    NegotiationThread,
    PortalToken,
)
from apps.quotations import services as quotation_services
from apps.quotations.models import Quotation

TOKEN_TTL_DAYS = 30


@transaction.atomic
def send_to_customer(quotation: Quotation, *, actor=None) -> PortalToken:
    """Mint a portal token and move the quote to SENT."""
    if not quotation.customer.contact_email:
        raise ValidationError("This customer has no contact email to send the quotation to")

    token = PortalToken.objects.create(
        customer=quotation.customer,
        quotation=quotation,
        expires_at=timezone.now() + timedelta(days=TOKEN_TTL_DAYS),
    )
    quotation_services.transition(quotation, QuotationStatus.SENT, actor=actor)
    quotation_services.record_event(
        quotation, QuotationEventType.SENT_TO_CUSTOMER, actor=actor, token=str(token.token)
    )
    record_event(
        quotation,
        kind=NegotiationEvent.Kind.SENT,
        author_type=NegotiationMessage.AuthorType.REP,
        actor=actor,
        body="Quotation sent for your review.",
    )
    return token


#: Internal status names leak process detail a customer shouldn't have to read
#: ("Pending Approval" invites "approval by whom, for what?"). These are the
#: customer-facing equivalents, plus whether the ball is in their court.
PORTAL_STATUS_LABELS: dict[str, tuple[str, bool]] = {
    QuotationStatus.SENT: ("Awaiting your review", True),
    QuotationStatus.UNDER_NEGOTIATION: ("Your request is with our team", False),
    QuotationStatus.PENDING_APPROVAL: ("Under internal review", False),
    QuotationStatus.APPROVED: ("Ready for your confirmation", True),
    QuotationStatus.CONFIRMED: ("Confirmed", False),
    QuotationStatus.REJECTED: ("Declined", False),
    QuotationStatus.CANCELLED: ("Closed", False),
    QuotationStatus.DRAFT: ("Being prepared", False),
}


def portal_status(status: str) -> tuple[str, bool]:
    return PORTAL_STATUS_LABELS.get(status, (status.replace("_", " ").title(), False))


def assert_portal_user(user):
    """Every portal route resolves the caller through their business."""
    profile = getattr(user, "customer_profile", None)
    if profile is None:
        raise PermissionDenied("This area is for customer accounts")
    return profile


def portal_profile(user) -> dict:
    """The customer's own account.

    Everything here except the password is read-only: the business name, tier
    and account manager are ours to set. A customer able to edit their own tier
    would be editing their own discount ceiling.
    """
    profile = assert_portal_user(user)
    quotations = Quotation.objects.filter(customer=profile)
    return {
        "login_email": user.email,
        "display_name": user.full_name or user.email,
        "company_name": profile.name,
        "tier": profile.tier,
        "currency": profile.currency,
        "contact_email": profile.contact_email,
        "account_manager": (
            profile.owner_rep.full_name or profile.owner_rep.email
            if profile.owner_rep_id
            else None
        ),
        "member_since": user.date_joined,
        "last_login": user.last_login,
        # Only what was actually sent to them; drafts stay private.
        "quotations_received": PortalToken.objects.filter(customer=profile)
        .values("quotation_id")
        .distinct()
        .count(),
        "quotations_confirmed": quotations.filter(
            status=QuotationStatus.CONFIRMED
        ).count(),
    }


def portal_quotations_for(user) -> list[Quotation]:
    """Every quotation this customer has been SENT, newest first.

    Scoped by `PortalToken`, not by customer — a quotation the rep is still
    drafting has no token, so it correctly stays invisible until sent. A
    quotation may have several tokens if it was re-sent; dedupe to the latest.
    """
    profile = getattr(user, "customer_profile", None)
    if profile is None:
        raise PermissionDenied("This area is for customer accounts")

    tokens = (
        PortalToken.objects.filter(customer=profile)
        .select_related("quotation", "quotation__customer")
        .order_by("-created_at")
    )

    seen: set[int] = set()
    quotations: list[Quotation] = []
    for token in tokens:
        if token.quotation_id in seen or not token.is_valid:
            continue
        seen.add(token.quotation_id)
        # Stash when it was sent; the list view shows it and the model has no
        # column of its own for it.
        token.quotation.sent_at = token.created_at
        quotations.append(token.quotation)

    quotations.sort(key=lambda q: q.sent_at, reverse=True)
    return quotations


def record_event(
    quotation: Quotation,
    *,
    kind: str,
    author_type: str,
    actor=None,
    body: str = "",
    discount_percent: Decimal | None = None,
    delivery_date=None,
    quotation_line_id: int | None = None,
    request: NegotiationRequest | None = None,
) -> NegotiationEvent:
    """Append one move to the negotiation log. Never updated, never deleted."""
    return NegotiationEvent.objects.create(
        quotation=quotation,
        request=request,
        kind=kind,
        author_type=author_type,
        author=actor,
        # Customers are shown as their company. "Acme Corp (portal)" is the
        # login's name, not a person, and reads like a bug in a conversation.
        author_name=(
            quotation.customer.name
            if author_type == NegotiationMessage.AuthorType.CUSTOMER
            else _name(actor)
        ),
        body=body or "",
        discount_percent=discount_percent,
        delivery_date=delivery_date,
        quotation_line_id=quotation_line_id,
    )


def negotiation_timeline(quotation: Quotation) -> list[dict]:
    """Every move, in the order it happened.

    A straight read of the append-only event log — no derivation from current
    state, so an offer that was later accepted still appears as the offer it
    was. Both sides render this identical list.
    """
    return [
        {
            "kind": event.kind,
            "author_type": event.author_type,
            "author_name": event.author_name or "System",
            "body": event.body,
            "discount_percent": event.discount_percent,
            "delivery_date": event.delivery_date,
            "line_description": (
                event.quotation_line.description if event.quotation_line_id else None
            ),
            "created_at": event.created_at,
        }
        for event in quotation.negotiation_events.select_related("quotation_line")
    ]


def open_request_for(quotation: Quotation) -> NegotiationRequest | None:
    """The round currently awaiting a reply, if any."""
    return (
        quotation.negotiation_requests.filter(
            status__in=[
                NegotiationRequestStatus.SUBMITTED,
                NegotiationRequestStatus.COUNTERED,
            ]
        )
        .order_by("-created_at")
        .first()
    )


def _name(user) -> str:
    if user is None:
        return "System"
    return user.full_name or user.email


@transaction.atomic
def post_message(
    quotation: Quotation,
    *,
    actor,
    body: str,
    author_type: str,
    quotation_line_id: int | None = None,
) -> NegotiationMessage:
    """Add a message to the thread without making a formal counter-offer.

    Used by both sides — asking a question shouldn't require proposing a
    number.
    """
    body = (body or "").strip()
    if not body:
        raise ValidationError("A message cannot be empty")

    thread, _ = NegotiationThread.objects.get_or_create(quotation=quotation)
    message = NegotiationMessage.objects.create(
        thread=thread,
        quotation_line_id=quotation_line_id,
        author_type=author_type,
        author=actor,
        body=body,
    )
    record_event(
        quotation,
        kind=NegotiationEvent.Kind.MESSAGE,
        author_type=author_type,
        actor=actor,
        body=body,
        quotation_line_id=quotation_line_id,
    )
    # Keeps the deal off the stalled-deals dashboard while people are talking.
    quotation_services.record_event(
        quotation,
        QuotationEventType.NEGOTIATION_OPENED
        if author_type == NegotiationMessage.AuthorType.REP
        else QuotationEventType.COUNTER_RECEIVED,
        actor=actor,
        note=body[:200],
    )
    return message


@transaction.atomic
def counter_request(
    request: NegotiationRequest,
    *,
    actor,
    counter_discount_percent: Decimal,
    note: str = "",
) -> NegotiationRequest:
    """Answer a customer's counter with a different number.

    Nothing is applied to the quotation yet — this is an offer. The discount
    only lands when the customer accepts it, which is what keeps the quoted
    figures honest while haggling is still in progress.
    """
    if request.status != NegotiationRequestStatus.SUBMITTED:
        raise ValidationError("This request has already been answered")
    counter_discount_percent = Decimal(counter_discount_percent)
    if not (Decimal("0") <= counter_discount_percent <= Decimal("100")):
        raise ValidationError("Counter discount must be between 0 and 100 percent")

    request.status = NegotiationRequestStatus.COUNTERED
    request.counter_discount_percent = counter_discount_percent
    request.resolved_by = actor
    request.resolved_at = timezone.now()
    request.resolution_note = note
    request.save()

    record_event(
        request.quotation,
        kind=NegotiationEvent.Kind.REP_COUNTER,
        author_type=NegotiationMessage.AuthorType.REP,
        actor=actor,
        body=note,
        discount_percent=counter_discount_percent,
        request=request,
    )
    quotation_services.record_event(
        request.quotation,
        QuotationEventType.NEGOTIATION_OPENED,
        actor=actor,
        note=f"Countered at {counter_discount_percent}%",
    )
    return request


@transaction.atomic
def accept_counter(request: NegotiationRequest, *, actor) -> Quotation:
    """The customer accepts the rep's counter-offer.

    Applies the REP's number, then goes through the same recalculation and
    re-approval path as any other change.
    """
    if request.status != NegotiationRequestStatus.COUNTERED:
        raise ValidationError("There is no counter-offer to accept on this request")
    if request.counter_discount_percent is None:
        raise ValidationError("That counter-offer has no discount to apply")

    quotation = request.quotation
    # An ORDER-level discount, exactly as in `accept_request`. This path used to
    # loop `update_line` and stamp the counter onto every line, which is the bug
    # that function's comment describes: a 12% counter silently CUT a line
    # already sitting at 18%, and flattening the per-line spread changed the
    # blended risk score the deal is governed by. The two accept paths differ
    # only in whose number is applied — the customer's ask here, the rep's
    # counter there — so they must apply it the same way.
    quotation.order_discount_percent = request.counter_discount_percent
    quotation.save(update_fields=["order_discount_percent", "updated_at"])

    # `requested_discount_percent` is deliberately left alone. It records what
    # the customer ASKED for; overwriting it with what they settled for would
    # rewrite the history the timeline is supposed to preserve.
    request.status = NegotiationRequestStatus.ACCEPTED
    request.save(update_fields=["status", "updated_at"])

    record_event(
        quotation,
        kind=NegotiationEvent.Kind.ACCEPTED,
        author_type=NegotiationMessage.AuthorType.CUSTOMER,
        actor=actor,
        body="Accepted your offer.",
        discount_percent=request.counter_discount_percent,
        request=request,
    )

    quotation_services.recalculate(quotation)
    quotation_services.record_event(
        quotation,
        QuotationEventType.COUNTER_ACCEPTED,
        actor=actor,
        note=f"Customer accepted our counter at {request.counter_discount_percent}%",
    )
    _settle_round(quotation, actor=actor, reprice=True)

    # The CUSTOMER accepted, so the deal is agreed. If the agreed terms need no
    # approval there is nothing left to decide, and leaving it at APPROVED made
    # them open the quotation a second time and press Confirm to say yes to
    # something they had just said yes to. Their acceptance is the confirmation.
    #
    # Deliberately not done on the rep-accepts path: there it is the rep who
    # agreed, and the customer has not placed the order yet — that one still
    # lands on APPROVED and waits for them.
    #
    # If the new terms DO breach a ceiling, _settle_round has already moved this
    # to PENDING_APPROVAL and the guard below leaves it there: the approvers
    # decide first, then the customer confirms.
    quotation.refresh_from_db()
    if quotation.status == QuotationStatus.APPROVED:
        quotation_services.confirm(quotation, actor=actor)
        quotation.refresh_from_db()
    return quotation


def _settle_round(quotation: Quotation, *, actor, reprice: bool) -> None:
    """Shared tail of every resolved negotiation round.

    Extracted so the rep-accepts, customer-accepts-our-counter and rep-declines
    paths cannot drift apart — the whole point is that re-approval is automatic
    regardless of who agreed, and that the quotation does not sit in
    UNDER_NEGOTIATION once nobody is negotiating.

    That second half is an invariant the UI leans on: a quotation is
    UNDER_NEGOTIATION **exactly while a round is open**. Without it the board's
    Negotiation column and the "awaiting you" inbox drifted in both directions —
    a resolved quote loitered in the column with nothing to act on, and an
    unanswered request sat on a quote parked in some other column entirely.

    `reprice` is False for a decline: nothing about the deal changed, so there
    is nothing to re-score and no reason to reopen approval.
    """
    if reprice and quotation.requires_approval:
        quotation_services.transition(quotation, QuotationStatus.PENDING_APPROVAL, actor=actor)
        from apps.approvals.services import open_approval_request

        open_approval_request(quotation, actor=actor)
        quotation_services.record_event(
            quotation,
            QuotationEventType.SUBMITTED,
            actor=actor,
            note="Negotiated terms exceed approval thresholds; re-entered approval automatically.",
        )
        return

    if (
        quotation.status == QuotationStatus.UNDER_NEGOTIATION
        and open_request_for(quotation) is None
    ):
        # APPROVED, not SENT: SENT is only ever reached from APPROVED, so the
        # quote was already cleared once and the terms now on it either breach
        # no ceiling (accepted) or are the ones that were cleared (declined).
        # The customer sees "Ready for your confirmation", which is exactly
        # where the ball now is.
        quotation_services.transition(quotation, QuotationStatus.APPROVED, actor=actor)


def authorise_portal_access(user, quotation_id: int) -> Quotation:
    """The portal's whole security model, in one function.

    Requires BOTH a customer session AND a token scoped to this quotation.
    Failures are 404, never 403 — we don't confirm that someone else's
    quotation exists.
    """
    profile = getattr(user, "customer_profile", None)
    if profile is None:
        raise PermissionDenied("This area is for customer accounts")

    token = (
        PortalToken.objects.filter(quotation_id=quotation_id, customer=profile)
        .order_by("-created_at")
        .first()
    )
    if token is None or not token.is_valid:
        raise NotFound()

    if token.used_at is None:
        token.used_at = timezone.now()
        token.save(update_fields=["used_at"])
    return token.quotation


@transaction.atomic
def submit_request(
    quotation: Quotation,
    *,
    actor,
    requested_discount_percent: Decimal | None = None,
    requested_delivery_date=None,
    message: str = "",
    line_comments: list[dict] | None = None,
) -> NegotiationRequest:
    """The customer's 'Submit Request' button."""
    if quotation.status not in (QuotationStatus.SENT, QuotationStatus.UNDER_NEGOTIATION):
        raise ValidationError("This quotation is not open for negotiation")
    # One round at a time. `open_request_for` has always spoken of "the round
    # currently awaiting a reply" in the singular, and every screen reads it
    # that way — but nothing stopped a second request being stacked on an
    # unanswered one. When the newer one was resolved the older was orphaned at
    # SUBMITTED forever: it kept the inbox's "awaiting you" count above zero on
    # a quotation that had already moved on, and no screen offered a way to
    # clear it.
    existing = open_request_for(quotation)
    if existing is not None:
        # SUBMITTED means the ball is with us: a second request stacked on an
        # unanswered one orphans the first at SUBMITTED forever, which is the
        # bug this guard was written for. Still refused.
        if existing.status == NegotiationRequestStatus.SUBMITTED:
            raise ValidationError(
                "You already have a request awaiting our response on this quotation.",
                negotiation_request_id=existing.id,
            )
        # COUNTERED means the ball is with THEM: we answered, and this new
        # request is their answer to that answer. Refusing it left the customer
        # with only two moves after our counter - take it or walk - when the
        # whole point of a negotiation is that it goes back and forth. The round
        # we countered is closed as declined (countering back IS declining the
        # number we named) and a fresh round opens, so the timeline reads as an
        # ordered exchange rather than one stalled round.
        existing.status = NegotiationRequestStatus.REJECTED
        existing.resolved_by = actor
        existing.resolved_at = timezone.now()
        existing.resolution_note = (
            f"Customer countered our {existing.counter_discount_percent}% offer "
            "with a new request."
        )
        existing.save()
    if requested_discount_percent is not None and not (
        Decimal("0") <= requested_discount_percent <= Decimal("100")
    ):
        raise ValidationError("Counter discount must be between 0 and 100 percent")

    thread, created = NegotiationThread.objects.get_or_create(quotation=quotation)
    for comment in line_comments or []:
        NegotiationMessage.objects.create(
            thread=thread,
            quotation_line_id=comment.get("quotation_line_id"),
            author_type=NegotiationMessage.AuthorType.CUSTOMER,
            author=actor,
            body=comment["body"],
        )
    # `message` is deliberately NOT also written as a standalone
    # NegotiationMessage — the request row carries it, and the timeline renders
    # it on the COUNTER_REQUEST entry. Doing both showed the customer's words
    # twice in a row.
    request = NegotiationRequest.objects.create(
        quotation=quotation,
        thread=thread,
        requested_discount_percent=requested_discount_percent,
        requested_delivery_date=requested_delivery_date,
        message=message,
    )
    record_event(
        quotation,
        kind=NegotiationEvent.Kind.COUNTER_REQUEST,
        author_type=NegotiationMessage.AuthorType.CUSTOMER,
        actor=actor,
        body=message,
        discount_percent=requested_discount_percent,
        delivery_date=requested_delivery_date,
        request=request,
    )

    if quotation.status == QuotationStatus.SENT:
        quotation_services.transition(quotation, QuotationStatus.UNDER_NEGOTIATION, actor=actor)
        quotation_services.record_event(
            quotation, QuotationEventType.NEGOTIATION_OPENED, actor=actor
        )
    quotation_services.record_event(
        quotation,
        QuotationEventType.COUNTER_RECEIVED,
        actor=actor,
        requested_discount=str(requested_discount_percent) if requested_discount_percent else None,
        note=message,
    )
    return request


@transaction.atomic
def accept_request(request: NegotiationRequest, *, actor) -> Quotation:
    """The rep accepts the counter-offer.

    Applies the requested discount to every line through the ordinary
    quotation service, so totals and the risk score recompute exactly as they
    would for a manual edit — and the quote re-enters approval on its own if
    the new terms breach a ceiling.
    """
    quotation = request.quotation
    if request.status != NegotiationRequestStatus.SUBMITTED:
        raise ValidationError("This request has already been resolved")

    if request.requested_discount_percent is not None:
        # The portal offers ONE "Counter Discount %" field, so the counter is an
        # ORDER-level ask, not a per-line one. Setting it here (rather than
        # stamping every line) matters twice over: it stops a 12% counter from
        # silently cutting a line that was already at 18%, and it preserves the
        # per-line discount structure the blended risk score is computed from.
        # recalculate() apportions the order discount down to the lines before
        # scoring, so ceilings are still enforced line by line.
        quotation.order_discount_percent = request.requested_discount_percent
        quotation.save(update_fields=["order_discount_percent", "updated_at"])

    request.status = NegotiationRequestStatus.ACCEPTED
    request.resolved_by = actor
    request.resolved_at = timezone.now()
    request.save()

    record_event(
        quotation,
        kind=NegotiationEvent.Kind.ACCEPTED,
        author_type=NegotiationMessage.AuthorType.REP,
        actor=actor,
        body="We've accepted your request.",
        discount_percent=request.requested_discount_percent,
        request=request,
    )
    quotation_services.recalculate(quotation)
    quotation_services.record_event(
        quotation, QuotationEventType.COUNTER_ACCEPTED, actor=actor,
        discount=str(request.requested_discount_percent),
    )

    _settle_round(quotation, actor=actor, reprice=True)
    return quotation


@transaction.atomic
def reject_request(request: NegotiationRequest, *, actor, note: str = "") -> NegotiationRequest:
    if request.status != NegotiationRequestStatus.SUBMITTED:
        raise ValidationError("This request has already been resolved")
    request.status = NegotiationRequestStatus.REJECTED
    request.resolved_by = actor
    request.resolved_at = timezone.now()
    request.resolution_note = note
    request.save()
    record_event(
        request.quotation,
        kind=NegotiationEvent.Kind.REJECTED,
        author_type=NegotiationMessage.AuthorType.REP,
        actor=actor,
        body=note or "We're unable to offer that discount.",
        request=request,
    )
    if request.thread_id:
        NegotiationMessage.objects.create(
            thread=request.thread,
            author_type=NegotiationMessage.AuthorType.REP,
            author=actor,
            body=note or "We're unable to offer that discount.",
        )
    # A decline ends the round as surely as an acceptance does. Leaving the
    # quotation in UNDER_NEGOTIATION afterwards stranded it in the board's
    # Negotiation column with nothing left to negotiate.
    _settle_round(request.quotation, actor=actor, reprice=False)
    return request


@transaction.atomic
def reject_by_customer(quotation: Quotation, *, actor, note: str = "") -> Quotation:
    """The customer declines the quotation outright.

    A rep cannot reject their own deal — that is why the sales side only offers
    accept or counter. Walking away is the customer's decision alone, and it
    has to be reachable at any point they can see the quote, otherwise a deal
    they have already refused sits open forever pretending to be live.

    Any round still in flight is closed at the same time, so the rep's panel
    stops asking for a reply to a conversation that is over.
    """
    rejectable = (
        QuotationStatus.SENT,
        QuotationStatus.UNDER_NEGOTIATION,
        QuotationStatus.APPROVED,
    )
    if quotation.status not in rejectable:
        raise ValidationError(
            "This quotation can no longer be declined in its current state."
        )

    open_request = open_request_for(quotation)
    if open_request is not None:
        open_request.status = NegotiationRequestStatus.REJECTED
        open_request.resolved_by = actor
        open_request.resolved_at = timezone.now()
        open_request.resolution_note = note or "Customer declined the quotation."
        open_request.save()

    record_event(
        quotation,
        kind=NegotiationEvent.Kind.REJECTED,
        author_type=NegotiationMessage.AuthorType.CUSTOMER,
        actor=actor,
        body=note or "Declined this quotation.",
        request=open_request,
    )
    quotation_services.transition(quotation, QuotationStatus.REJECTED, actor=actor)
    quotation_services.record_event(
        quotation,
        QuotationEventType.REJECTED,
        actor=actor,
        note=note or "Declined by the customer.",
    )
    return quotation


@transaction.atomic
def confirm_by_customer(quotation: Quotation, *, actor) -> dict:
    """The customer's 'Confirm Quotation' button.

    Delegates to the shared confirm path, which re-scores first — so if the
    negotiated terms exceed thresholds the order does NOT go to fulfillment,
    it goes back to approval.
    """
    # APPROVED belongs here. The brief's own loop is: customer counters ->
    # rep accepts -> quote re-enters approval -> approvers clear it -> customer
    # confirms. That last step lands on APPROVED, and leaving it out dead-ended
    # the negotiation flow at the final click, while `portal_status` was
    # already telling the customer it was "Ready for your confirmation".
    confirmable = (
        QuotationStatus.SENT,
        QuotationStatus.UNDER_NEGOTIATION,
        QuotationStatus.APPROVED,
    )
    if quotation.status not in confirmable:
        raise ValidationError(
            "This quotation cannot be confirmed yet — it is still being reviewed."
        )

    # A customer must not be able to confirm out from under their own open
    # change request. Without this the request is orphaned at SUBMITTED forever:
    # the rep never accepts or rejects it, nobody is told, and the customer has
    # silently accepted terms they were in the middle of disputing.
    #
    # Deliberately SUBMITTED only, not every open round. A COUNTERED request has
    # already been answered — the customer has seen our offer, so confirming is
    # an informed "I'll take the original terms", not a silent acceptance of
    # something they were disputing. Blocking that would trap them, because
    # there is no "decline our counter" action for them to reach for.
    open_request = NegotiationRequest.objects.filter(
        quotation=quotation, status=NegotiationRequestStatus.SUBMITTED
    ).first()
    if open_request is not None:
        raise ValidationError(
            "You have a change request awaiting a response. Your sales rep must accept or "
            "decline it before this quotation can be confirmed.",
            negotiation_request_id=open_request.id,
        )

    return quotation_services.confirm(quotation, actor=actor)
