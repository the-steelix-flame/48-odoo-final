from datetime import datetime
from decimal import Decimal

from ninja import Schema


class QuotationLineOut(Schema):
    id: int
    product_id: int
    variant_id: int | None = None
    line_type: str
    description: str
    category_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    allowed_discount_percent: Decimal
    discount_excess_points: Decimal
    is_over_limit: bool
    tax_percent: Decimal
    line_subtotal: Decimal
    line_total: Decimal
    margin_amount: Decimal

    @staticmethod
    def resolve_category_name(obj) -> str:
        return obj.product.category.name


class QuotationSummaryOut(Schema):
    """The card on the Kanban board (screen 3)."""

    id: int
    number: str
    customer_id: int
    customer_name: str
    customer_tier: str
    owner_rep_id: int
    owner_rep_name: str
    status: str
    currency: str
    total: Decimal
    margin_percent: Decimal
    blended_risk_score: Decimal
    risk_band: str
    requires_approval: bool
    idle_days: int
    created_at: datetime
    last_activity_at: datetime

    # These three are reached down a relation, so they need a resolver when the
    # source is a Quotation (the list endpoint). But api.py::_detail() builds a
    # plain dict that already carries the finished values, and Ninja hands the
    # RAW dict to a resolver — `dict.customer` then raises AttributeError, the
    # field is dropped, and every endpoint returning QuotationDetailOut fails
    # response validation with "Field required". Handling both shapes keeps the
    # list and the detail paths working through one schema.

    @staticmethod
    def resolve_customer_name(obj) -> str:
        if isinstance(obj, dict):
            return obj["customer_name"]
        return obj.customer.name

    @staticmethod
    def resolve_customer_tier(obj) -> str:
        if isinstance(obj, dict):
            return obj["customer_tier"]
        return obj.customer.tier

    @staticmethod
    def resolve_owner_rep_name(obj) -> str:
        if isinstance(obj, dict):
            return obj["owner_rep_name"]
        return obj.owner_rep.full_name or obj.owner_rep.email


class LineRiskOut(Schema):
    line_id: int | None = None
    label: str
    discount_percent: Decimal
    allowed_percent: Decimal
    excess_points: Decimal
    weight: Decimal
    is_over: bool


class RiskBreakdownOut(Schema):
    """Serialised straight from the risk engine's dataclass, unreshaped."""

    score: Decimal
    band: str
    requires_approval: bool
    worst_line_excess: Decimal
    blended_excess: Decimal
    order_level_excess: Decimal
    effective_order_discount: Decimal
    explanation: str
    lines: list[LineRiskOut]


class QuotationEventOut(Schema):
    id: int
    event_type: str
    actor_name: str
    note: str
    payload: dict
    created_at: datetime

    @staticmethod
    def resolve_actor_name(obj) -> str:
        return obj.actor.full_name or obj.actor.email if obj.actor_id else "System"


class QuotationDetailOut(QuotationSummaryOut):
    """Returned by EVERY quotation mutation, fully recomputed.

    The frontend never calculates money or risk — it renders what the backend
    decided. That's how the live `OVER (+8pt)` badge and the approval screen
    can never disagree.
    """

    order_discount_percent: Decimal
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    margin_amount: Decimal
    price_list_id: int | None = None
    lines: list[QuotationLineOut]
    risk: RiskBreakdownOut
    events: list[QuotationEventOut]


class CreateQuotationIn(Schema):
    customer_id: int
    price_list_id: int | None = None


class AddLineIn(Schema):
    product_id: int
    variant_id: int | None = None
    quantity: Decimal = Decimal("1")
    discount_percent: Decimal = Decimal("0")
    from_upsell: bool = False


class UpdateLineIn(Schema):
    quantity: Decimal | None = None
    discount_percent: Decimal | None = None


class OrderDiscountIn(Schema):
    order_discount_percent: Decimal


class ConfirmOut(Schema):
    """What POST /quotations/{id}/confirm returns.

    This exists because the endpoint previously declared no response schema.
    Ninja then falls back to raw json.dumps, which cannot serialise the Django
    model instances _detail() puts in `lines` and `events` — so confirm
    committed its work and *then* raised, leaving the caller with a 500 on an
    order that had actually gone through.
    """

    confirmed: bool
    quotation: QuotationDetailOut
    fulfillment_plan_id: int | None = None
    subscription_ids: list[int] = []
    invoice_id: int | None = None
    #: Set when the quote re-entered approval instead of confirming.
    reason: str | None = None
