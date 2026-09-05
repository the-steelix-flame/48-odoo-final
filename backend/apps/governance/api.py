"""Discount ceilings & approval chain configuration (screen 18).  Owner: sinjeki."""

from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth, require_role
from apps.common.enums import Role
from apps.governance.models import (
    ApprovalRule,
    CategoryDiscountCeiling,
    RiskConfig,
    TierDiscountCeiling,
)

router = Router(auth=internal_auth)


class TierCeilingOut(Schema):
    id: int
    tier: str
    max_discount_percent: Decimal


class CategoryCeilingOut(Schema):
    id: int
    category_id: int
    category_name: str
    max_discount_percent: Decimal

    @staticmethod
    def resolve_category_name(obj) -> str:
        return obj.category.name


class ApprovalRuleOut(Schema):
    id: int
    name: str
    band: str
    min_score: Decimal
    max_score: Decimal
    required_roles: list[str]
    sequence: int
    is_active: bool


class RiskConfigOut(Schema):
    weight_worst: Decimal
    weight_blended: Decimal
    weight_order: Decimal
    cap_worst: Decimal
    cap_blended: Decimal
    cap_order: Decimal
    high_band_threshold: Decimal


class GovernanceConfigOut(Schema):
    """One call powers the whole of screen 18."""

    tier_ceilings: list[TierCeilingOut]
    category_ceilings: list[CategoryCeilingOut]
    approval_rules: list[ApprovalRuleOut]
    risk_config: RiskConfigOut


class CeilingIn(Schema):
    max_discount_percent: Decimal


class ApprovalRuleIn(Schema):
    name: str
    band: str
    min_score: Decimal
    max_score: Decimal
    required_roles: list[str]
    sequence: int = 0
    is_active: bool = True


@router.get("/config", response=GovernanceConfigOut)
def get_config(request):
    return {
        "tier_ceilings": list(TierDiscountCeiling.objects.all()),
        "category_ceilings": list(
            CategoryDiscountCeiling.objects.select_related("category").all()
        ),
        "approval_rules": list(ApprovalRule.objects.all()),
        "risk_config": RiskConfig.get_solo(),
    }


@router.patch("/tier-ceilings/{ceiling_id}", response=TierCeilingOut)
def update_tier_ceiling(request, ceiling_id: int, payload: CeilingIn):
    require_role(request, Role.ADMIN, Role.SALES_MANAGER)
    obj = TierDiscountCeiling.objects.get(pk=ceiling_id)
    obj.max_discount_percent = payload.max_discount_percent
    obj.save(update_fields=["max_discount_percent", "updated_at"])
    return obj


@router.patch("/category-ceilings/{ceiling_id}", response=CategoryCeilingOut)
def update_category_ceiling(request, ceiling_id: int, payload: CeilingIn):
    require_role(request, Role.ADMIN, Role.SALES_MANAGER)
    obj = CategoryDiscountCeiling.objects.select_related("category").get(pk=ceiling_id)
    obj.max_discount_percent = payload.max_discount_percent
    obj.save(update_fields=["max_discount_percent", "updated_at"])
    return obj


@router.patch("/approval-rules/{rule_id}", response=ApprovalRuleOut)
def update_approval_rule(request, rule_id: int, payload: ApprovalRuleIn):
    require_role(request, Role.ADMIN, Role.SALES_MANAGER)
    rule = ApprovalRule.objects.get(pk=rule_id)
    for key, value in payload.dict().items():
        setattr(rule, key, value)
    rule.full_clean()
    rule.save()
    return rule
