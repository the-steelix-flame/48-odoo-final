"""Customer portal (screen 11) + the rep's side of negotiation.
Owner: the-steelix-flame.

Mounted at /api/portal/. This is a SEPARATE router with a SEPARATE serialiser,
not the internal quotation router with a flag. `PortalQuotationOut` has no
cost, no margin, no risk score and no approval history — margin data has no
code path that reaches a customer.
"""

from datetime import date, datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import any_auth, internal_auth
from apps.common.errors import NotFound
from apps.negotiation import services
from apps.negotiation.models import NegotiationRequest
from apps.quotations.models import Quotation

router = Router()


# --------------------------------------------------------------------------
# Customer-facing schemas — deliberately narrow.
# --------------------------------------------------------------------------
class PortalLineOut(Schema):
    id: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    line_total: Decimal
    # NOTE: no unit_cost, no margin_amount, no allowed_discount_percent,
    # no discount_excess_points. Not filtered out — never included.


class TimelineEntryOut(Schema):
    """One entry in the shared negotiation thread.

    `kind` is MESSAGE | COUNTER_REQUEST | REP_COUNTER | ACCEPTED | REJECTED.
    Both sides render this same list.
    """

    kind: str
    author_type: str
    author_name: str
    body: str
    discount_percent: Decimal | None = None
    delivery_date: date | None = None
    line_description: str | None = None
    created_at: datetime


class PortalRequestOut(Schema):
    id: int
    requested_discount_percent: Decimal | None = None
    requested_delivery_date: date | None = None
    #: What we offered back, when we countered rather than accepting.
    counter_discount_percent: Decimal | None = None
    message: str
    status: str
    resolution_note: str
    created_at: datetime


class PortalQuotationRowOut(Schema):
    """One row of the customer's quotation list. Deliberately thin."""

    id: int
    number: str
    status: str
    #: Customer-facing wording; `status` stays for the frontend's own logic.
    status_label: str
    #: True when the customer is the one holding things up.
    action_required: bool
    currency: str
    total: Decimal
    line_count: int
    sent_at: datetime | None = None


class PortalQuotationOut(Schema):
    id: int
    number: str
    status: str
    status_label: str
    action_required: bool
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    valid_until: date | None = None
    company_name: str
    lines: list[PortalLineOut]
    timeline: list[TimelineEntryOut]
    requests: list[PortalRequestOut]
    #: The round awaiting a reply, if any. Non-null with a
    #: `counter_discount_percent` means the ball is with the customer.
    open_request: PortalRequestOut | None = None


class SubmitRequestIn(Schema):
    requested_discount_percent: Decimal | None = None
    requested_delivery_date: date | None = None
    message: str = ""
    line_comments: list[dict] = []


# Shared by both sides — defined here because the portal routes below reference
# them, and a Ninja route's annotations are evaluated at import time.
class MessageIn(Schema):
    body: str
    quotation_line_id: int | None = None


class CounterIn(Schema):
    counter_discount_percent: Decimal
    note: str = ""


class ResolveIn(Schema):
    note: str = ""


class NegotiationOut(Schema):
    """The rep's view of the conversation, on the quotation itself."""

    quotation_id: int
    quotation_number: str
    customer_name: str
    status: str
    has_thread: bool
    timeline: list[TimelineEntryOut]
    open_request: PortalRequestOut | None = None
    requests: list[PortalRequestOut]


# --------------------------------------------------------------------------
# Customer routes — token-scoped
# --------------------------------------------------------------------------
def _portal_payload(quotation: Quotation) -> dict:
    label, action_required = services.portal_status(quotation.status)
    open_request = services.open_request_for(quotation)
    # A counter waiting on the customer is also "your move", even if the
    # quotation status alone wouldn't say so. Keyed on COUNTERED rather than on
    # the number being present — only a countered request is an offer.
    if open_request is not None and open_request.status == "COUNTERED":
        action_required = True
        label = "We've made you an offer"
    elif open_request is None and quotation.status == "UNDER_NEGOTIATION":
        # Every round is settled, so the ball is back with the customer even
        # though the quotation status still says negotiation. Without this the
        # portal kept saying "your request is with our team" after we'd already
        # answered it.
        action_required = True
        label = "Terms agreed — ready for your confirmation"
    return {
        "id": quotation.id,
        "number": quotation.number,
        "status": quotation.status,
        "status_label": label,
        "action_required": action_required,
        "currency": quotation.currency,
        "subtotal": quotation.subtotal,
        "discount_total": quotation.discount_total,
        "tax_total": quotation.tax_total,
        "total": quotation.total,
        "valid_until": quotation.valid_until,
        "company_name": quotation.customer.name,
        "lines": list(quotation.lines.all()),
        "timeline": services.negotiation_timeline(quotation),
        "requests": list(quotation.negotiation_requests.all()),
        "open_request": open_request,
    }


@router.get("/quotations", response=list[PortalQuotationRowOut], auth=any_auth)
def portal_list_quotations(request):
    """Every quotation this customer has been sent.

    Without this the portal had no index at all — a customer could log in and
    had no way to reach anything, because access is per-quotation by token and
    nothing listed the tokens they held.
    """
    rows = []
    for quotation in services.portal_quotations_for(request.auth):
        label, action_required = services.portal_status(quotation.status)
        rows.append(
            {
                "id": quotation.id,
                "number": quotation.number,
                "status": quotation.status,
                "status_label": label,
                "action_required": action_required,
                "currency": quotation.currency,
                "total": quotation.total,
                "line_count": quotation.lines.count(),
                "sent_at": getattr(quotation, "sent_at", None),
            }
        )
    return rows


@router.get("/quotations/{quotation_id}", response=PortalQuotationOut, auth=any_auth)
def portal_get_quotation(request, quotation_id: int):
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    return _portal_payload(quotation)


@router.post("/quotations/{quotation_id}/requests", response=PortalQuotationOut, auth=any_auth)
def portal_submit_request(request, quotation_id: int, payload: SubmitRequestIn):
    """Submit Request — comments, a counter discount, a delivery date."""
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    services.submit_request(
        quotation,
        actor=request.auth,
        requested_discount_percent=payload.requested_discount_percent,
        requested_delivery_date=payload.requested_delivery_date,
        message=payload.message,
        line_comments=payload.line_comments,
    )
    quotation.refresh_from_db()
    return _portal_payload(quotation)


@router.post("/quotations/{quotation_id}/messages", response=PortalQuotationOut, auth=any_auth)
def portal_post_message(request, quotation_id: int, payload: MessageIn):
    """Ask a question without proposing a number."""
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    services.post_message(
        quotation,
        actor=request.auth,
        body=payload.body,
        author_type="CUSTOMER",
        quotation_line_id=payload.quotation_line_id,
    )
    quotation.refresh_from_db()
    return _portal_payload(quotation)


@router.post(
    "/quotations/{quotation_id}/requests/{request_id}/accept",
    response=PortalQuotationOut,
    auth=any_auth,
)
def portal_accept_counter(request, quotation_id: int, request_id: int):
    """Customer accepts the discount we offered back.

    Goes through the same recalculation and re-approval path as any other
    change to the quotation.
    """
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    negotiation_request = _get_request(request_id)
    if negotiation_request.quotation_id != quotation.id:
        raise NotFound("Negotiation request not found")
    services.accept_counter(negotiation_request, actor=request.auth)
    quotation.refresh_from_db()
    return _portal_payload(quotation)


@router.post("/quotations/{quotation_id}/confirm", response=PortalQuotationOut, auth=any_auth)
def portal_confirm(request, quotation_id: int):
    """Confirm Quotation.

    If the negotiated terms exceed thresholds the quote re-enters approval
    instead of going to fulfillment — the customer sees the status change.
    """
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    services.confirm_by_customer(quotation, actor=request.auth)
    quotation.refresh_from_db()
    return _portal_payload(quotation)


# --------------------------------------------------------------------------
# Internal routes — the rep's side of the same conversation
# --------------------------------------------------------------------------
@router.post("/internal/quotations/{quotation_id}/send", auth=internal_auth)
def send_to_customer(request, quotation_id: int):
    """Mint the portal link and move the quote to SENT."""
    try:
        quotation = Quotation.objects.select_related("customer").get(pk=quotation_id)
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")
    token = services.send_to_customer(quotation, actor=request.auth)
    return {
        "token": str(token.token),
        "portal_url": f"/portal/quotations/{quotation.id}",
        "expires_at": token.expires_at,
    }


@router.get(
    "/internal/quotations/{quotation_id}/negotiation",
    response=NegotiationOut,
    auth=internal_auth,
)
def get_negotiation(request, quotation_id: int):
    """The rep's view of the conversation, rendered on the quotation itself.

    Same `timeline` the customer sees — one shared record of who said what, so
    neither side can be looking at a different story.
    """
    try:
        quotation = Quotation.objects.select_related("customer").get(pk=quotation_id)
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")

    return {
        "quotation_id": quotation.id,
        "quotation_number": quotation.number,
        "customer_name": quotation.customer.name,
        "status": quotation.status,
        "has_thread": hasattr(quotation, "negotiation_thread"),
        "timeline": services.negotiation_timeline(quotation),
        "open_request": services.open_request_for(quotation),
        "requests": list(quotation.negotiation_requests.all()),
    }


@router.post(
    "/internal/quotations/{quotation_id}/messages",
    response=NegotiationOut,
    auth=internal_auth,
)
def post_rep_message(request, quotation_id: int, payload: MessageIn):
    """Reply to the customer without changing any numbers."""
    try:
        quotation = Quotation.objects.select_related("customer").get(pk=quotation_id)
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")
    services.post_message(
        quotation,
        actor=request.auth,
        body=payload.body,
        author_type="REP",
        quotation_line_id=payload.quotation_line_id,
    )
    return get_negotiation(request, quotation_id)


@router.post(
    "/internal/requests/{request_id}/counter",
    response=NegotiationOut,
    auth=internal_auth,
)
def counter_request(request, request_id: int, payload: CounterIn):
    """Answer a counter-offer with a different number.

    Nothing is applied to the quotation yet — the discount only lands if the
    customer accepts, which keeps the quoted figures honest mid-haggle.
    """
    negotiation_request = _get_request(request_id)
    services.counter_request(
        negotiation_request,
        actor=request.auth,
        counter_discount_percent=payload.counter_discount_percent,
        note=payload.note,
    )
    return get_negotiation(request, negotiation_request.quotation_id)


@router.get("/internal/requests", response=list[PortalRequestOut], auth=internal_auth)
def list_requests(request, status: str | None = None):
    qs = NegotiationRequest.objects.select_related("quotation")
    if status:
        qs = qs.filter(status=status)
    return list(qs)


@router.post("/internal/requests/{request_id}/accept", auth=internal_auth)
def accept_request(request, request_id: int):
    """Accept the counter-offer; risk is re-scored and approval may reopen."""
    negotiation_request = _get_request(request_id)
    quotation = services.accept_request(negotiation_request, actor=request.auth)
    return {
        "quotation_id": quotation.id,
        "status": quotation.status,
        "risk_band": quotation.risk_band,
        "blended_risk_score": quotation.blended_risk_score,
        "re_entered_approval": quotation.status == "PENDING_APPROVAL",
    }


@router.post("/internal/requests/{request_id}/reject", auth=internal_auth)
def reject_request(request, request_id: int, payload: ResolveIn):
    services.reject_request(_get_request(request_id), actor=request.auth, note=payload.note)
    return {"ok": True}


def _get_request(request_id: int) -> NegotiationRequest:
    try:
        return NegotiationRequest.objects.select_related("quotation", "thread").get(pk=request_id)
    except NegotiationRequest.DoesNotExist:
        raise NotFound("Negotiation request not found")
