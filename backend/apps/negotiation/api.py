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

from apps.accounts.auth import any_auth, internal_auth, require_role
from apps.common.enums import NegotiationRequestStatus, QuotationStatus, Role
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
    """Internal-only. The rep inbox needs to know WHICH deal a counter-offer is
    against — without it the screen shows "someone wants 20% off" and nothing
    else. Added by @sinjeki for the negotiation inbox; @the-steelix-flame please
    sanity-check, this is your lane."""

    id: int
    quotation_id: int
    quotation_number: str
    customer_name: str
    requested_discount_percent: Decimal | None = None
    requested_delivery_date: date | None = None
    #: What we offered back, when we countered rather than accepting.
    counter_discount_percent: Decimal | None = None
    message: str
    status: str
    resolution_note: str
    created_at: datetime

    @staticmethod
    def resolve_quotation_number(obj) -> str:
        return obj.quotation.number

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.quotation.customer.name


class PortalBillLineOut(Schema):
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


class PortalBillOut(Schema):
    """The bill, as the customer sees it. Null until Finance signs off."""

    id: int
    number: str
    issue_date: date
    due_date: date
    currency: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    is_paid: bool
    status: str
    sales_rep: str
    lines: list[PortalBillLineOut]


class PortalBillHistoryOut(Schema):
    """One line of the customer's own billing history on this order."""

    id: int
    number: str
    issue_date: date
    invoice_type: str
    period_start: date | None = None
    period_end: date | None = None
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    is_paid: bool


class PayIn(Schema):
    reference: str = ""


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
    #: What the rep has taken off, as a share of the pre-discount subtotal.
    effective_discount_percent: Decimal


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
    #: What the rep has taken off, as a share of the pre-discount subtotal.
    #: Computed here so the portal renders a number rather than deriving one.
    effective_discount_percent: Decimal
    company_name: str
    #: Null until Finance or a Sales Manager accepts the final deal.
    bill: PortalBillOut | None = None
    #: Every invoice on this order. `bill` is the one they are dealing with
    #: now; this is so a customer who has paid more than once can see all of
    #: their own payments rather than just the most recent.
    bill_history: list[PortalBillHistoryOut] = []
    #: Only set once the bill is paid; despatch is not promised before then.
    shipping_status: str | None = None
    lines: list[PortalLineOut]
    timeline: list[TimelineEntryOut]
    requests: list[PortalRequestOut]
    #: The round awaiting a reply, if any. Non-null with a
    #: `counter_discount_percent` means the ball is with the customer.
    open_request: PortalRequestOut | None = None


class PortalProfileOut(Schema):
    """The customer's own account, as they see it.

    Read-only apart from the password: the business name, tier and account
    manager are ours to set, not theirs to edit — a customer promoting
    themselves to Gold would rewrite their own discount ceiling.
    """

    login_email: str
    display_name: str
    company_name: str
    tier: str
    currency: str
    contact_email: str
    account_manager: str | None = None
    member_since: datetime | None = None
    last_login: datetime | None = None
    quotations_received: int
    quotations_confirmed: int


class ChangePasswordIn(Schema):
    current_password: str
    new_password: str


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
def _effective_discount(quotation: Quotation) -> Decimal:
    """Total taken off, as a percentage of the pre-discount subtotal.

    The lines each carry their own percentage, but an order-level discount sits
    on top of them, so no single line answers "how much did they give us?".
    """
    subtotal = Decimal(quotation.subtotal or 0)
    if subtotal <= 0:
        return Decimal("0.00")
    return (Decimal(quotation.discount_total or 0) / subtotal * Decimal(100)).quantize(
        Decimal("0.01")
    )


def _portal_payload(quotation: Quotation) -> dict:
    label, action_required = services.portal_status_for(quotation)
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

    # The customer asked for a number and we simply said yes. To them that is a
    # settled answer, not a negotiation still running, and the portal was
    # describing it in negotiation language either way. Only where we accepted
    # THEIR figure — a countered round is a different conversation, and one we
    # already label above.
    latest_request = quotation.negotiation_requests.order_by("-created_at").first()
    plainly_accepted = (
        open_request is None
        and latest_request is not None
        and latest_request.status == NegotiationRequestStatus.ACCEPTED
        and latest_request.counter_discount_percent is None
    )
    # Not while it is still with our approvers: "accepted" would be true of the
    # request and misleading about the deal.
    if plainly_accepted and quotation.status in (
        QuotationStatus.SENT,
        QuotationStatus.APPROVED,
        QuotationStatus.UNDER_NEGOTIATION,
    ):
        label = "Your request was accepted"
        action_required = True
    # What the customer is shown is what we last SENT them, not wherever the
    # deal has since got to internally. A rep accepting a counter rewrites the
    # order discount immediately — the approvers need the real number — but
    # until someone presses "Send to customer" again, none of that is the
    # customer's to see. Falls back to live figures for a quotation with no
    # snapshot, which is any that predates this.
    sent = services.sent_terms_for(quotation)
    money = sent or {
        "subtotal": quotation.subtotal,
        "discount_total": quotation.discount_total,
        "tax_total": quotation.tax_total,
        "total": quotation.total,
        "effective_discount_percent": _effective_discount(quotation),
        "lines": list(quotation.lines.all()),
    }

    return {
        "id": quotation.id,
        "number": quotation.number,
        "status": quotation.status,
        "status_label": label,
        "action_required": action_required,
        "currency": quotation.currency,
        "subtotal": money["subtotal"],
        "discount_total": money["discount_total"],
        "tax_total": money["tax_total"],
        "total": money["total"],
        "valid_until": quotation.valid_until,
        "effective_discount_percent": money["effective_discount_percent"],
        "company_name": quotation.customer.name,
        "bill": services.portal_bill(quotation),
        "bill_history": services.portal_bill_history(quotation),
        "shipping_status": services.portal_shipping(quotation),
        "lines": money["lines"],
        "timeline": services.negotiation_timeline(quotation),
        "requests": list(quotation.negotiation_requests.all()),
        "open_request": open_request,
    }


@router.get("/profile", response=PortalProfileOut, auth=any_auth)
def portal_profile(request):
    """The signed-in customer's own account."""
    return services.portal_profile(request.auth)


@router.post("/profile/password", auth=any_auth)
def portal_change_password(request, payload: ChangePasswordIn):
    """Change your own password. The current one is the proof of identity."""
    from apps.accounts import staff

    services.assert_portal_user(request.auth)
    staff.change_own_password(
        request.auth,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return {"ok": True, "detail": "Your password has been changed."}


@router.get("/quotations", response=list[PortalQuotationRowOut], auth=any_auth)
def portal_list_quotations(request):
    """Every quotation this customer has been sent.

    Without this the portal had no index at all — a customer could log in and
    had no way to reach anything, because access is per-quotation by token and
    nothing listed the tokens they held.
    """
    rows = []
    for quotation in services.portal_quotations_for(request.auth):
        label, action_required = services.portal_status_for(quotation)
        # Same rule as the detail view: the list shows what was sent, so a
        # total cannot move here while an internal decision is still in flight.
        sent = services.sent_terms_for(quotation)
        rows.append(
            {
                "id": quotation.id,
                "number": quotation.number,
                "status": quotation.status,
                "status_label": label,
                "action_required": action_required,
                "currency": quotation.currency,
                "total": sent["total"] if sent else quotation.total,
                "line_count": (
                    len(sent["lines"]) if sent else quotation.lines.count()
                ),
                "sent_at": getattr(quotation, "sent_at", None),
                "effective_discount_percent": (
                    sent["effective_discount_percent"]
                    if sent
                    else _effective_discount(quotation)
                ),
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


@router.post("/quotations/{quotation_id}/reject", response=PortalQuotationOut, auth=any_auth)
def portal_reject(request, quotation_id: int, payload: ResolveIn):
    """Decline the quotation.

    Only the customer gets this. A rep countering their own deal is a
    negotiation; a rep rejecting it is just deleting their own work.
    """
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    services.reject_by_customer(quotation, actor=request.auth, note=payload.note)
    quotation.refresh_from_db()
    return _portal_payload(quotation)


@router.post("/quotations/{quotation_id}/pay", response=PortalQuotationOut, auth=any_auth)
def portal_pay(request, quotation_id: int, payload: PayIn):
    """Settle the bill in full."""
    quotation = services.authorise_portal_access(request.auth, quotation_id)
    services.pay_bill(quotation, actor=request.auth, reference=payload.reference)
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
#: Negotiating is the rep's job, and only the rep's. A Sales Manager or Finance
#: user governs the deal — they approve or refuse the terms the rep brings them
#: — and haggling directly with the customer would put them on both sides of
#: their own approval. Reading the conversation stays open to every internal
#: role, because an approver has to see what was said to judge it.
MAY_NEGOTIATE = (Role.SALES_REP,)
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

    return _negotiation_payload(quotation)


def _negotiation_payload(quotation: Quotation) -> dict:
    """One shape for the rep's negotiation view.

    Shared so that any endpoint which changes the conversation can hand back the
    conversation, rather than the caller having to fetch it again afterwards.
    """
    quotation.refresh_from_db()
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
    require_role(request, *MAY_NEGOTIATE)
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
    qs = NegotiationRequest.objects.select_related("quotation", "quotation__customer")
    if status:
        qs = qs.filter(status=status)
    return list(qs)


@router.post(
    "/internal/requests/{request_id}/accept",
    response=NegotiationOut,
    auth=internal_auth,
)
def accept_request(request, request_id: int):
    """Accept the counter-offer; risk is re-scored and approval may reopen.

    Returns the whole conversation, like every other endpoint that changes it.
    It used to return a small summary dict, so the panel accepted and then POSTed
    to `/internal/quotations/{id}/negotiation` to refresh — a GET-only route,
    which answered 405. The accept had already succeeded by then, so the deal
    moved while the screen showed an error.
    """
    require_role(request, *MAY_NEGOTIATE)
    negotiation_request = _get_request(request_id)
    quotation = services.accept_request(negotiation_request, actor=request.auth)
    return _negotiation_payload(quotation)


# There is deliberately NO rep-side reject endpoint.
#
# A seller declining their own deal is just deleting their own work; the rep's
# two answers are accept or counter. Walking away belongs to the customer, via
# POST /api/portal/quotations/{id}/reject.
#
# Removed at the API boundary rather than only hidden in the UI, so the rule is
# actually enforced — a button re-added later gets a 404 and a conversation,
# instead of silently working. `services.reject_request` survives because it
# also settles a quote out of UNDER_NEGOTIATION and a test pins that behaviour;
# nothing routes to it today.


def _get_request(request_id: int) -> NegotiationRequest:
    try:
        return NegotiationRequest.objects.select_related("quotation", "thread").get(pk=request_id)
    except NegotiationRequest.DoesNotExist:
        raise NotFound("Negotiation request not found")
