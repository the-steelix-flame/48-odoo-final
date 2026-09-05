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


class PortalMessageOut(Schema):
    id: int
    quotation_line_id: int | None = None
    line_description: str | None = None
    author_type: str
    body: str
    created_at: datetime

    @staticmethod
    def resolve_line_description(obj) -> str | None:
        return obj.quotation_line.description if obj.quotation_line_id else None


class PortalRequestOut(Schema):
    id: int
    requested_discount_percent: Decimal | None = None
    requested_delivery_date: date | None = None
    message: str
    status: str
    resolution_note: str
    created_at: datetime


class PortalQuotationOut(Schema):
    id: int
    number: str
    status: str
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    total: Decimal
    valid_until: date | None = None
    company_name: str
    lines: list[PortalLineOut]
    messages: list[PortalMessageOut]
    requests: list[PortalRequestOut]


class SubmitRequestIn(Schema):
    requested_discount_percent: Decimal | None = None
    requested_delivery_date: date | None = None
    message: str = ""
    line_comments: list[dict] = []


class ResolveIn(Schema):
    note: str = ""


# --------------------------------------------------------------------------
# Customer routes — token-scoped
# --------------------------------------------------------------------------
def _portal_payload(quotation: Quotation) -> dict:
    thread = getattr(quotation, "negotiation_thread", None)
    return {
        "id": quotation.id,
        "number": quotation.number,
        "status": quotation.status,
        "currency": quotation.currency,
        "subtotal": quotation.subtotal,
        "discount_total": quotation.discount_total,
        "tax_total": quotation.tax_total,
        "total": quotation.total,
        "valid_until": quotation.valid_until,
        "company_name": quotation.customer.name,
        "lines": list(quotation.lines.all()),
        "messages": list(thread.messages.select_related("quotation_line")) if thread else [],
        "requests": list(quotation.negotiation_requests.all()),
    }


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
