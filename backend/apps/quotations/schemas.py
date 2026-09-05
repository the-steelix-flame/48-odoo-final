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

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.customer.name

    @staticmethod
    def resolve_customer_tier(obj) -> str:
        return obj.customer.tier

    @staticmethod
    def resolve_owner_rep_name(obj) -> str:
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
