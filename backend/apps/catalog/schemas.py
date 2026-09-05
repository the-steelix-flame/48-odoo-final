from decimal import Decimal

from ninja import Schema


class CategoryOut(Schema):
    id: int
    name: str
    code: str


class ProductOut(Schema):
    id: int
    name: str
    sku: str
    category_id: int
    category_name: str
    description: str
    unit: str
    base_price: Decimal
    tax_percent: Decimal
    is_subscription: bool
    recurring_plan_id: int | None = None
    is_promoted: bool
    is_active: bool
    variant_count: int = 0
    quantity_on_hand: int = 0

    @staticmethod
    def resolve_category_name(obj) -> str:
        return obj.category.name

    @staticmethod
    def resolve_variant_count(obj) -> int:
        return obj.variants.count()


class ProductDetailOut(ProductOut):
    """Adds cost and margin. Internal routers only — never the portal."""

    cost_price: Decimal
    margin_percent: Decimal


class ProductIn(Schema):
    name: str
    sku: str
    category_id: int
    description: str = ""
    unit: str = "Each"
    base_price: Decimal
    cost_price: Decimal
    tax_percent: Decimal = Decimal("0")
    is_subscription: bool = False
    recurring_plan_id: int | None = None
    is_promoted: bool = False


class PriceListOut(Schema):
    id: int
    name: str
    tier: str | None = None
    currency: str
    is_active: bool


class UpsellSuggestionOut(Schema):
    """What the panel beside the cart renders (screen 4)."""

    product_id: int
    product_name: str
    unit_price: Decimal
    margin_delta: Decimal
    score: float
    is_promoted: bool
    promo_label: str | None = None
