"""Price list resolution.  Owner: sinjeki.

One function, used by the quotation builder, the upsell panel and the portal,
so a product costs the same amount no matter who asks.
"""

from __future__ import annotations

from decimal import Decimal

from apps.catalog.models import PriceList, PriceListRule, Product, ProductVariant


def resolve_unit_price(
    product: Product,
    price_list: PriceList | None = None,
    variant: ProductVariant | None = None,
) -> Decimal:
    """Base price + variant extra, then the most specific price list rule.

    Specificity order: product rule > category rule > list-wide rule. Ties are
    broken by `priority` descending.
    """
    price = Decimal(product.base_price)
    if variant is not None:
        price += Decimal(variant.extra_price)

    if price_list is None or not price_list.is_active:
        return _q(price)

    rule = _best_rule(price_list, product)
    if rule is None:
        return _q(price)

    if rule.rule_type == PriceListRule.RuleType.FIXED:
        return _q(Decimal(rule.value))
    return _q(price * (Decimal(1) - Decimal(rule.value) / Decimal(100)))


def _best_rule(price_list: PriceList, product: Product) -> PriceListRule | None:
    rules = list(price_list.rules.all())
    for predicate in (
        lambda r: r.product_id == product.id,
        lambda r: r.product_id is None and r.category_id == product.category_id,
        lambda r: r.product_id is None and r.category_id is None,
    ):
        matches = [r for r in rules if predicate(r)]
        if matches:
            return max(matches, key=lambda r: r.priority)
    return None


def _q(value: Decimal) -> Decimal:
    """Quantise to 2dp. Money is never a float and never has 7 decimal places."""
    return Decimal(value).quantize(Decimal("0.01"))
