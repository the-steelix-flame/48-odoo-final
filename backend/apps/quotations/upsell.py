"""Upsell / cross-sell ranking (screen 4's side panel).  Owner: the-steelix-flame.

Ranked by co-purchase score, boosted by promotion, floored by margin. The
margin floor is the interesting rule: a suggestion that would dilute the deal
is never shown, no matter how strongly it correlates.
"""

from __future__ import annotations

from decimal import Decimal

from apps.catalog.models import ProductPairing, UpsellConfig
from apps.catalog.pricing import resolve_unit_price
from apps.quotations.models import Quotation

CORROBORATION_BONUS = Decimal("0.10")


def suggestions_for(quotation: Quotation, limit: int = 3) -> list[dict]:
    cart_product_ids = set(quotation.lines.values_list("product_id", flat=True))
    if not cart_product_ids:
        return []

    config = UpsellConfig.get_solo()
    pairings = (
        ProductPairing.objects.filter(
            source_product_id__in=cart_product_ids, is_active=True
        )
        .exclude(target_product_id__in=cart_product_ids)
        .select_related("target_product", "target_product__category")
    )

    scored: dict[int, dict] = {}
    for pairing in pairings:
        product = pairing.target_product
        if not product.is_active:
            continue

        unit_price = resolve_unit_price(product, quotation.price_list)
        if unit_price <= 0:
            continue
        margin_percent = (unit_price - Decimal(product.cost_price)) / unit_price * Decimal(100)
        # The margin floor. A strong correlation is not a reason to lose money.
        if margin_percent < Decimal(config.min_margin_percent):
            continue

        entry = scored.get(product.id)
        if entry is None:
            score = Decimal(pairing.co_purchase_score)
            if product.is_promoted:
                score += Decimal(config.promoted_boost)
            entry = {
                "product_id": product.id,
                "product_name": product.name,
                "unit_price": unit_price,
                "margin_delta": (unit_price - Decimal(product.cost_price)).quantize(
                    Decimal("0.01")
                ),
                "score": score,
                "is_promoted": product.is_promoted,
                "promo_label": "Promoted" if product.is_promoted else None,
            }
            scored[product.id] = entry
        else:
            # Suggested by more than one thing already in the cart — that's
            # corroboration, and it should outrank a single strong pairing.
            entry["score"] += CORROBORATION_BONUS

    ranked = sorted(scored.values(), key=lambda e: e["score"], reverse=True)[:limit]
    for entry in ranked:
        entry["score"] = float(entry["score"])
    return ranked
