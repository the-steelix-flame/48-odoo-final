from django.contrib import admin

from apps.governance.models import (
    ApprovalRule,
    CategoryDiscountCeiling,
    RiskConfig,
    TierDiscountCeiling,
)

admin.site.register([TierDiscountCeiling, CategoryDiscountCeiling, ApprovalRule, RiskConfig])
