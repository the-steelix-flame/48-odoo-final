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
    QuotationStatus.REJECTED: ("Closed", False),
    QuotationStatus.CANCELLED: ("Closed", False),
    QuotationStatus.DRAFT: ("Being prepared", False),
}


def portal_status(status: str) -> tuple[str, bool]:
    return PORTAL_STATUS_LABELS.get(status, (status.replace("_", " ").title(), False))


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


def negotiation_timeline(quotation: Quotation) -> list[dict]:
    """One chronological thread of the whole negotiation.

    Merges free-text messages with the state changes on each
    `NegotiationRequest`, so "they asked 20%, we offered 15%, they accepted"
    reads as three entries in order rather than as two tables the reader has to
    interleave in their head. Both sides render the SAME list — that's what
    makes the conversation trustworthy.
    """
    thread = getattr(quotation, "negotiation_thread", None)
    entries: list[dict] = []

    if thread is not None:
        for message in thread.messages.select_related("quotation_line", "author"):
            entries.append(
                {
                    "kind": "MESSAGE",
                    "author_type": message.author_type,
                    # Customers are shown as their company, not as the portal
                    # login's name ("Acme Corp (portal)" reads like a bug).
                    "author_name": (
                        quotation.customer.name
                        if message.author_type == NegotiationMessage.AuthorType.CUSTOMER
                        else _name(message.author)
                    ),
                    "body": message.body,
                    "discount_percent": None,
                    "delivery_date": None,
                    "line_description": (
                        message.quotation_line.description if message.quotation_line_id else None
                    ),
                    "created_at": message.created_at,
                }
            )

    for request in quotation.negotiation_requests.select_related("resolved_by"):
        # What the customer asked for.
        entries.append(
            {
                "kind": "COUNTER_REQUEST",
                "author_type": NegotiationMessage.AuthorType.CUSTOMER,
                "author_name": quotation.customer.name,
                "body": request.message,
                "discount_percent": request.requested_discount_percent,
                "delivery_date": request.requested_delivery_date,
                "line_description": None,
                "created_at": request.created_at,
            }
        )

        if request.status == NegotiationRequestStatus.SUBMITTED or request.resolved_at is None:
            continue

        # How we answered.
        kind = {
            NegotiationRequestStatus.ACCEPTED: "ACCEPTED",
            NegotiationRequestStatus.REJECTED: "REJECTED",
            NegotiationRequestStatus.COUNTERED: "REP_COUNTER",
        }[request.status]
        entries.append(
            {
                "kind": kind,
                "author_type": NegotiationMessage.AuthorType.REP,
                "author_name": _name(request.resolved_by),
                "body": request.resolution_note,
                # On ACCEPTED, the agreed figure is our counter when we made
                # one, otherwise the customer's original ask.
                "discount_percent": request.counter_discount_percent
                if kind == "REP_COUNTER"
                else (
                    request.counter_discount_percent
                    if request.counter_discount_percent is not None
                    else request.requested_discount_percent
                )
                if kind == "ACCEPTED"
                else None,
                "delivery_date": None,
                "line_description": None,
                "created_at": request.resolved_at,
            }
        )

    entries.sort(key=lambda entry: entry["created_at"])
    return entries


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

    # The note lives on `resolution_note` and is rendered on the REP_COUNTER
    # timeline entry. Writing it as a separate message too would show our words
    # twice, exactly as the customer's message used to.
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
    for line in quotation.lines.all():
        quotation_services.update_line(
            quotation, line.id, discount_percent=request.counter_discount_percent, actor=actor
        )

    # `requested_discount_percent` is deliberately left alone. It records what
    # the customer ASKED for; overwriting it with what they settled for would
    # rewrite the history the timeline is supposed to preserve.
    request.status = NegotiationRequestStatus.ACCEPTED
    request.save(update_fields=["status", "updated_at"])

    quotation_services.recalculate(quotation)
    quotation_services.record_event(
        quotation,
        QuotationEventType.COUNTER_ACCEPTED,
        actor=actor,
        note=f"Customer accepted our counter at {request.counter_discount_percent}%",
    )
    _reapprove_if_needed(quotation, actor=actor)
    return quotation


def _reapprove_if_needed(quotation: Quotation, *, actor) -> None:
    """Shared tail of every accepted negotiation.

    Extracted so the rep-accepts path and the customer-accepts-our-counter path
    cannot drift apart — the whole point is that re-approval is automatic
    regardless of who agreed.
    """
    if not quotation.requires_approval:
        return
    quotation_services.transition(quotation, QuotationStatus.PENDING_APPROVAL, actor=actor)
    from apps.approvals.services import open_approval_request

    open_approval_request(quotation, actor=actor)
    quotation_services.record_event(
        quotation,
        QuotationEventType.SUBMITTED,
        actor=actor,
        note="Negotiated terms exceed approval thresholds; re-entered approval automatically.",
    )


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

    quotation_services.recalculate(quotation)
    quotation_services.record_event(
        quotation, QuotationEventType.COUNTER_ACCEPTED, actor=actor,
        discount=str(request.requested_discount_percent),
    )

    _reapprove_if_needed(quotation, actor=actor)
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
    if request.thread_id:
        NegotiationMessage.objects.create(
            thread=request.thread,
            author_type=NegotiationMessage.AuthorType.REP,
            author=actor,
            body=note or "We're unable to offer that discount.",
        )
    return request


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
