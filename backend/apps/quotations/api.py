"""Quotation list, builder and upsell panel (screens 3, 4).  Owner: the-steelix-flame.

Routers stay thin: parse, authorise, delegate to services, serialise.
No business rules below this line.
"""

from ninja import Router

from apps.accounts.auth import internal_auth
from apps.accounts.models import Customer
from apps.catalog.models import PriceList, UpsellSuggestionLog
from apps.catalog.schemas import UpsellSuggestionOut
from apps.common.errors import NotFound
from apps.quotations import services
from apps.quotations.models import Quotation
from apps.quotations.schemas import (
    AddLineIn,
    ConfirmOut,
    CreateQuotationIn,
    OrderDiscountIn,
    QuotationDetailOut,
    QuotationSummaryOut,
    UpdateLineIn,
)
from apps.quotations.upsell import suggestions_for

router = Router(auth=internal_auth)


def _detail(quotation: Quotation) -> dict:
    """Assemble the full recomputed payload every mutation returns."""
    quotation.refresh_from_db()
    data = {
        field: getattr(quotation, field)
        for field in (
            "id", "number", "customer_id", "owner_rep_id", "status", "currency",
            "total", "margin_percent", "blended_risk_score", "risk_band",
            "requires_approval", "created_at", "last_activity_at",
            "order_discount_percent", "subtotal", "discount_total", "tax_total",
            "margin_amount", "price_list_id",
        )
    }
    data.update(
        customer_name=quotation.customer.name,
        customer_tier=quotation.customer.tier,
        owner_rep_name=quotation.owner_rep.full_name or quotation.owner_rep.email,
        idle_days=quotation.idle_days,
        lines=list(quotation.lines.select_related("product", "product__category")),
        risk=services.risk_breakdown(quotation),
        events=list(quotation.events.select_related("actor")),
    )
    return data


def _get(quotation_id: int) -> Quotation:
    try:
        return Quotation.objects.select_related("customer", "owner_rep", "price_list").get(
            pk=quotation_id
        )
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")


@router.get("/", response=list[QuotationSummaryOut])
def list_quotations(request, status: str | None = None, owner_rep_id: int | None = None):
    qs = Quotation.objects.select_related("customer", "owner_rep")
    if status:
        qs = qs.filter(status=status)
    if owner_rep_id:
        qs = qs.filter(owner_rep_id=owner_rep_id)
    return list(qs)


@router.post("/", response=QuotationDetailOut)
def create_quotation(request, payload: CreateQuotationIn):
    try:
        customer = Customer.objects.get(pk=payload.customer_id)
    except Customer.DoesNotExist:
        raise NotFound("Customer not found")
    price_list = (
        PriceList.objects.filter(pk=payload.price_list_id).first()
        if payload.price_list_id
        else None
    )
    quotation = services.create_quotation(
        customer=customer, owner_rep=request.auth, price_list=price_list
    )
    return _detail(quotation)


@router.get("/{quotation_id}", response=QuotationDetailOut)
def get_quotation(request, quotation_id: int):
    return _detail(_get(quotation_id))


@router.post("/{quotation_id}/lines", response=QuotationDetailOut)
def add_line(request, quotation_id: int, payload: AddLineIn):
    quotation = _get(quotation_id)
    services.add_line(
        quotation,
        product_id=payload.product_id,
        variant_id=payload.variant_id,
        quantity=payload.quantity,
        discount_percent=payload.discount_percent,
        actor=request.auth,
        from_upsell=payload.from_upsell,
    )
    if payload.from_upsell:
        UpsellSuggestionLog.objects.create(
            quotation=quotation,
            product_id=payload.product_id,
            action=UpsellSuggestionLog.Action.ADDED,
            margin_delta=0,
            actor=request.auth,
        )
    return _detail(quotation)


@router.patch("/{quotation_id}/lines/{line_id}", response=QuotationDetailOut)
def update_line(request, quotation_id: int, line_id: int, payload: UpdateLineIn):
    quotation = _get(quotation_id)
    services.update_line(
        quotation,
        line_id,
        quantity=payload.quantity,
        discount_percent=payload.discount_percent,
        actor=request.auth,
    )
    return _detail(quotation)


@router.delete("/{quotation_id}/lines/{line_id}", response=QuotationDetailOut)
def remove_line(request, quotation_id: int, line_id: int):
    quotation = _get(quotation_id)
    services.remove_line(quotation, line_id, actor=request.auth)
    return _detail(quotation)


@router.patch("/{quotation_id}/order-discount", response=QuotationDetailOut)
def set_order_discount(request, quotation_id: int, payload: OrderDiscountIn):
    quotation = _get(quotation_id)
    quotation.order_discount_percent = payload.order_discount_percent
    quotation.save(update_fields=["order_discount_percent", "updated_at"])
    services.recalculate(quotation)
    return _detail(quotation)


@router.post("/{quotation_id}/submit", response=QuotationDetailOut)
def submit_quotation(request, quotation_id: int):
    """Auto-routes. The rep never asks for approval — the score decides."""
    quotation = _get(quotation_id)
    services.submit(quotation, actor=request.auth)
    return _detail(quotation)


@router.post("/{quotation_id}/confirm", response=ConfirmOut)
def confirm_quotation(request, quotation_id: int):
    """Confirm the order: plan the split, start subscriptions, issue invoices.

    Re-scores first, so a quote whose terms drifted during negotiation goes
    back to approval instead of straight to fulfillment.
    """
    quotation = _get(quotation_id)
    result = services.confirm(quotation, actor=request.auth)
    return {
        "confirmed": result["confirmed"],
        "quotation": _detail(quotation),
        "fulfillment_plan_id": result.get("fulfillment_plan_id"),
        "subscription_ids": result.get("subscription_ids", []),
        "invoice_id": result.get("invoice_id"),
        "reason": result.get("reason"),
    }


@router.get("/{quotation_id}/upsell", response=list[UpsellSuggestionOut])
def get_upsell_suggestions(request, quotation_id: int):
    return suggestions_for(_get(quotation_id))


@router.post("/{quotation_id}/upsell/{product_id}/dismiss")
def dismiss_suggestion(request, quotation_id: int, product_id: int):
    UpsellSuggestionLog.objects.create(
        quotation=_get(quotation_id),
        product_id=product_id,
        action=UpsellSuggestionLog.Action.DISMISSED,
        margin_delta=0,
        actor=request.auth,
    )
    return {"ok": True}
