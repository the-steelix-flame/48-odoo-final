"""The blended discount risk engine.  Owner: the-steelix-flame.

★ PURE FUNCTION. No database access, no Django imports, no model instances.
  Plain data in, a dataclass out. That is what makes it unit-testable before
  the models exist, reusable by the portal's re-approval path, and safe to
  serialise straight to screen 6 without reshaping.

The rule in one sentence: every line is judged against ITS OWN ceiling
(the stricter of the customer tier and the product category), and the score
blends the single worst offender with the value-weighted pattern across the
whole order, so neither one bad line nor many small ones slips through.

See WORKFLOW.md §4 for the worked examples this module is tested against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")


def _d(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class RiskConfigData:
    """Mirror of the RiskConfig model, without the ORM."""

    weight_worst: Decimal = Decimal("0.50")
    weight_blended: Decimal = Decimal("0.30")
    weight_order: Decimal = Decimal("0.20")
    cap_worst: Decimal = Decimal("10")
    cap_blended: Decimal = Decimal("5")
    cap_order: Decimal = Decimal("5")
    high_band_threshold: Decimal = Decimal("60")

    @classmethod
    def from_model(cls, obj) -> "RiskConfigData":
        return cls(
            weight_worst=_d(obj.weight_worst),
            weight_blended=_d(obj.weight_blended),
            weight_order=_d(obj.weight_order),
            cap_worst=_d(obj.cap_worst),
            cap_blended=_d(obj.cap_blended),
            cap_order=_d(obj.cap_order),
            high_band_threshold=_d(obj.high_band_threshold),
        )


@dataclass(frozen=True)
class LineInput:
    """One quotation line, reduced to only what scoring needs."""

    line_id: int | None
    label: str
    line_subtotal: Decimal  # qty × unit_price, BEFORE discount
    discount_percent: Decimal
    category_ceiling: Decimal


@dataclass
class LineRisk:
    """Per-line verdict. Rendered as the `OVER (+8pt)` badge and screen 6's table."""

    line_id: int | None
    label: str
    discount_percent: Decimal
    allowed_percent: Decimal
    excess_points: Decimal
    weight: Decimal
    is_over: bool


@dataclass
class RiskBreakdown:
    """The complete verdict. Serialised as-is to the API."""

    score: Decimal
    band: str  # "NONE" | "MEDIUM" | "HIGH"
    requires_approval: bool
    worst_line_excess: Decimal
    blended_excess: Decimal
    order_level_excess: Decimal
    effective_order_discount: Decimal
    lines: list[LineRisk] = field(default_factory=list)
    explanation: str = ""


def score_quotation(
    lines: list[LineInput],
    tier_ceiling: Decimal,
    order_discount_percent: Decimal = ZERO,
    config: RiskConfigData | None = None,
) -> RiskBreakdown:
    """Compute the blended risk score for a quotation.

    Args:
        lines: every line, with its own category ceiling already resolved.
        tier_ceiling: the customer's tier ceiling (Gold = 15).
        order_discount_percent: an order-level discount applied on top of
            line discounts.
        config: weights and caps; defaults match the seeded RiskConfig.

    Returns:
        A RiskBreakdown. `band == "NONE"` means auto-approve.
    """
    cfg = config or RiskConfigData()
    tier_ceiling = _d(tier_ceiling)
    order_discount_percent = _d(order_discount_percent)

    if not lines:
        return RiskBreakdown(
            score=ZERO,
            band="NONE",
            requires_approval=False,
            worst_line_excess=ZERO,
            blended_excess=ZERO,
            order_level_excess=ZERO,
            effective_order_discount=ZERO,
            explanation="Empty quotation.",
        )

    gross = sum((_d(ln.line_subtotal) for ln in lines), ZERO)

    line_risks: list[LineRisk] = []
    worst = ZERO
    blended = ZERO
    line_discount_value = ZERO

    for ln in lines:
        subtotal = _d(ln.line_subtotal)
        given = _d(ln.discount_percent)
        # The stricter of the two ceilings wins. This single line is the
        # reason a Gold customer can still be flagged on a Services item.
        allowed = min(tier_ceiling, _d(ln.category_ceiling))
        excess = max(ZERO, given - allowed)
        weight = (subtotal / gross) if gross else ZERO

        worst = max(worst, excess)
        blended += excess * weight
        line_discount_value += subtotal * given / Decimal(100)

        line_risks.append(
            LineRisk(
                line_id=ln.line_id,
                label=ln.label,
                discount_percent=given,
                allowed_percent=allowed,
                excess_points=_round(excess),
                weight=_round(weight, "0.0001"),
                is_over=excess > ZERO,
            )
        )

    # Order-level discount stacks on top of what the lines already gave away.
    after_lines = gross - line_discount_value
    order_discount_value = after_lines * order_discount_percent / Decimal(100)
    total_discount_value = line_discount_value + order_discount_value
    effective = (total_discount_value / gross * Decimal(100)) if gross else ZERO
    order_level = max(ZERO, effective - tier_ceiling)

    score = Decimal(100) * (
        cfg.weight_worst * _capped(worst, cfg.cap_worst)
        + cfg.weight_blended * _capped(blended, cfg.cap_blended)
        + cfg.weight_order * _capped(order_level, cfg.cap_order)
    )
    score = _round(score)

    # Round once, here, so the API, the badge and the explanation sentence all
    # quote identical numbers. Nothing erodes trust in a demo faster than the
    # summary saying 2.400 while the table says 2.40.
    worst = _round(worst)
    blended = _round(blended)
    order_level = _round(order_level)

    # A quote is clean only if no line broke its own ceiling AND the order as a
    # whole stayed within the tier. Either breach opens an approval.
    requires_approval = worst > ZERO or order_level > ZERO
    if not requires_approval:
        band = "NONE"
    elif score < cfg.high_band_threshold:
        band = "MEDIUM"
    else:
        band = "HIGH"

    return RiskBreakdown(
        score=score,
        band=band,
        requires_approval=requires_approval,
        worst_line_excess=worst,
        blended_excess=blended,
        order_level_excess=order_level,
        effective_order_discount=_round(effective),
        lines=line_risks,
        explanation=_explain(band, blended, order_level, line_risks),
    )


def _capped(value: Decimal, cap: Decimal) -> Decimal:
    if cap <= ZERO:
        return ZERO
    return min(Decimal(1), value / cap)


def _round(value: Decimal, exp: str = "0.01") -> Decimal:
    return Decimal(value).quantize(Decimal(exp))


def _explain(
    band: str,
    blended: Decimal,
    order_level: Decimal,
    line_risks: list[LineRisk],
) -> str:
    """Human sentence for screen 6's 'Why This Quote Was Flagged' panel."""
    if band == "NONE":
        return "Every line is within its own discount ceiling and the order total is within the customer tier limit."

    over = [lr for lr in line_risks if lr.is_over]
    parts: list[str] = []
    if len(over) == 1:
        lr = over[0]
        parts.append(
            f"{lr.label} is {lr.excess_points} points over its {lr.allowed_percent}% ceiling."
        )
    elif len(over) > 1:
        worst_line = max(over, key=lambda lr: lr.excess_points)
        parts.append(
            f"{len(over)} lines exceed their ceilings; the worst is {worst_line.label} "
            f"at {worst_line.excess_points} points over."
        )
    if blended > ZERO and len(over) > 1:
        parts.append(
            f"Value-weighted across the order that averages {blended:.2f} points of excess."
        )
    if order_level > ZERO:
        parts.append(
            f"The order-level discount is {order_level} points above the customer tier ceiling."
        )
    return " ".join(parts)


def chain_for_band(band: str, rules: list) -> list[str]:
    """Look up the approval chain for a band from ApprovalRule rows.

    `rules` are ApprovalRule model instances (or anything with `.band`,
    `.required_roles`, `.is_active`). Falls back to sensible defaults so a
    missing config row never silently auto-approves a risky quote.
    """
    for rule in rules:
        if getattr(rule, "is_active", True) and rule.band == band:
            return list(rule.required_roles)
    return {
        "NONE": [],
        "MEDIUM": ["SALES_MANAGER"],
        "HIGH": ["FINANCE"],
    }[band]
