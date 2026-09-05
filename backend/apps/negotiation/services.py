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
    if message:
        NegotiationMessage.objects.create(
            thread=thread,
            author_type=NegotiationMessage.AuthorType.CUSTOMER,
            author=actor,
            body=message,
        )

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
        for line in quotation.lines.all():
            quotation_services.update_line(
                quotation,
                line.id,
                discount_percent=request.requested_discount_percent,
                actor=actor,
            )

    request.status = NegotiationRequestStatus.ACCEPTED
    request.resolved_by = actor
    request.resolved_at = timezone.now()
    request.save()

    quotation_services.recalculate(quotation)
    quotation_services.record_event(
        quotation, QuotationEventType.COUNTER_ACCEPTED, actor=actor,
        discount=str(request.requested_discount_percent),
    )

    if quotation.requires_approval:
        quotation_services.transition(quotation, QuotationStatus.PENDING_APPROVAL, actor=actor)
        from apps.approvals.services import open_approval_request

        open_approval_request(quotation, actor=actor)
        quotation_services.record_event(
            quotation,
            QuotationEventType.SUBMITTED,
            actor=actor,
            note="Negotiated terms exceed approval thresholds; re-entered approval automatically.",
        )
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
    if quotation.status not in (QuotationStatus.SENT, QuotationStatus.UNDER_NEGOTIATION):
        raise ValidationError("This quotation cannot be confirmed in its current state")
    return quotation_services.confirm(quotation, actor=actor)
