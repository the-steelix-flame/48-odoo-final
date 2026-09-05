"""Upsell / cross-sell ranking (screen 4's side panel).  Owner: the-steelix-flame.

Ranked by co-purchase score, boosted by promotion, floored by margin. The
margin floor is the interesting rule: a suggestion that would dilute the deal
is never shown, no matter how strongly it correlates.

Two tiers, in this order:

  1. Pairings — "people who bought X also bought Y". Evidence-based.
  2. Recurring plans — active subscription products. A support SLA or a care
     plan attaches to almost anything, so it needs no co-purchase history to
     be a sensible offer.

Tier 2 exists because a plan an admin created five minutes ago has no pairing
rows at all, and without this it could never be suggested however good an
offer it is.

One slot is *reserved* for tier 2 whenever the cart has no recurring line yet.
Without the reservation a cart with three strong pairings — a laptop, say —
fills every slot and the rep is never once prompted to attach a service plan,
which is the single highest-margin thing they could add. When the cart already
has a recurring line the reservation is dropped, because the prompt has served
its purpose and correlation is the better use of the space.
"""

from __future__ import annotations

from decimal import Decimal

from apps.catalog.models import Product, ProductPairing, UpsellConfig
from apps.catalog.pricing import resolve_unit_price
from apps.common.enums import LineType
from apps.quotations.models import Quotation

CORROBORATION_BONUS = Decimal("0.10")

#: How a cadence reads in the panel. Falls back to the plan's own label, so a
#: cadence added to RecurringInterval still renders sensibly without an edit.
INTERVAL_LABELS = {
    "WEEKLY": "Weekly",
    "MONTHLY": "Monthly",
    "QUARTERLY": "Quarterly",
    "YEARLY": "Yearly",
    "BIENNIAL": "Every 2 years",
}


def _priced(product, quotation, config) -> tuple[Decimal, Decimal] | None:
    """Unit price and margin, or None if the product fails the margin floor.

    Shared by both tiers on purpose — two copies of a money rule is how the
    floor silently drifts between them.
    """
    unit_price = resolve_unit_price(product, quotation.price_list)
    if unit_price <= 0:
        return None
    margin = unit_price - Decimal(product.cost_price)
    margin_percent = margin / unit_price * Decimal(100)
    # The margin floor. A strong correlation is not a reason to lose money.
    if margin_percent < Decimal(config.min_margin_percent):
        return None
    return unit_price, margin


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

        priced = _priced(product, quotation, config)
        if priced is None:
            continue
        unit_price, margin = priced

        entry = scored.get(product.id)
        if entry is None:
            score = Decimal(pairing.co_purchase_score)
            if product.is_promoted:
                score += Decimal(config.promoted_boost)
            entry = {
                "product_id": product.id,
                "product_name": product.name,
                "unit_price": unit_price,
                "margin_delta": margin.quantize(Decimal("0.01")),
                "score": score,
                "is_promoted": product.is_promoted,
                "promo_label": "Promoted" if product.is_promoted else None,
                "plan_label": None,
            }
            scored[product.id] = entry
        else:
            # Suggested by more than one thing already in the cart — that's
            # corroboration, and it should outrank a single strong pairing.
            entry["score"] += CORROBORATION_BONUS

    # Hold one slot back for a service plan unless the cart already has one.
    has_recurring = quotation.lines.filter(line_type=LineType.RECURRING).exists()
    reserved = 0 if has_recurring else 1
    pairing_slots = max(limit - reserved, 1) if limit > 1 else limit

    ranked = sorted(scored.values(), key=lambda e: e["score"], reverse=True)[:pairing_slots]

    if len(ranked) < limit:
        ranked.extend(
            _recurring_fillers(
                quotation,
                config,
                exclude=cart_product_ids | {e["product_id"] for e in ranked},
                slots=limit - len(ranked),
            )
        )

    for entry in ranked:
        entry["score"] = float(entry["score"])
    return ranked


def _recurring_fillers(quotation, config, *, exclude: set[int], slots: int) -> list[dict]:
    """Active subscription products, for the slots pairings didn't fill.

    A plan is only offerable once it is attached to a product — the plan is the
    billing policy, the product is the thing with a price. A plan with no
    product is deliberately invisible here rather than being shown as something
    a rep cannot actually add to the quote.
    """
    if slots <= 0:
        return []

    candidates = (
        Product.objects.filter(
            is_active=True,
            is_subscription=True,
            recurring_plan__isnull=False,
            recurring_plan__is_active=True,
        )
        .exclude(id__in=exclude)
        .select_related("recurring_plan")
        .order_by("-is_promoted", "name")
    )

    fillers: list[dict] = []
    for product in candidates:
        if len(fillers) >= slots:
            break
        priced = _priced(product, quotation, config)
        if priced is None:
            continue
        unit_price, margin = priced
        plan = product.recurring_plan
        fillers.append(
            {
                "product_id": product.id,
                "product_name": product.name,
                "unit_price": unit_price,
                "margin_delta": margin.quantize(Decimal("0.01")),
                # Negative so that if these are ever re-sorted alongside tier 1
                # they still land underneath it. Ordering is not an accident
                # here: no co-purchase evidence means no claim to the top slot.
                "score": Decimal("-1"),
                "is_promoted": product.is_promoted,
                "promo_label": "Promoted" if product.is_promoted else None,
                "plan_label": INTERVAL_LABELS.get(
                    plan.interval, plan.get_interval_display()
                ),
            }
        )
    return fillers
