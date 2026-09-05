from django.db import models

from apps.common.enums import CustomerTier, RiskBand, Role
from apps.common.models import PERCENT, TimeStampedModel, percent


class TierDiscountCeiling(TimeStampedModel):
    """Bronze 5%, Silver 10%, Gold 15%. Screen 18, top-left panel."""

    tier = models.CharField(max_length=10, choices=CustomerTier.choices, unique=True)
    max_discount_percent = models.DecimalField(**PERCENT)

    class Meta:
        db_table = "tier_discount_ceiling"

    def __str__(self) -> str:
        return f"{self.tier} ≤ {self.max_discount_percent}%"


class CategoryDiscountCeiling(TimeStampedModel):
    """Hardware 15%, Services 10%. Screen 18, top-right panel.

    This is the table that makes one bad Services line flag a Gold quote.
    """

    category = models.OneToOneField(
        "catalog.ProductCategory", on_delete=models.CASCADE, related_name="discount_ceiling"
    )
    max_discount_percent = models.DecimalField(**PERCENT)

    class Meta:
        db_table = "category_discount_ceiling"

    def __str__(self) -> str:
        return f"{self.category.name} ≤ {self.max_discount_percent}%"


class ApprovalRule(TimeStampedModel):
    """The approval chain, as data. Screen 18, bottom panel.

    `required_roles` is an ordered JSON list, e.g. ["SALES_MANAGER","FINANCE"].
    An empty list means auto-approve. This is why "chains are configurable" is
    a true statement about the system rather than a claim about a constant.
    """

    name = models.CharField(max_length=120)
    band = models.CharField(max_length=10, choices=RiskBand.choices)
    min_score = models.DecimalField(**PERCENT)
    max_score = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    required_roles = models.JSONField(default=list)
    sequence = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "approval_rule"
        ordering = ["sequence"]

    def __str__(self) -> str:
        chain = " → ".join(self.required_roles) or "auto-approve"
        return f"{self.name}: {chain}"

    def clean(self):
        from django.core.exceptions import ValidationError

        bad = [r for r in self.required_roles if r not in Role.values]
        if bad:
            raise ValidationError(f"Unknown roles in chain: {bad}")


class RiskConfig(TimeStampedModel):
    """Singleton (pk=1). Tuning the score is a config change, not a deploy."""

    weight_worst = models.DecimalField(max_digits=4, decimal_places=2, default=0.50)
    weight_blended = models.DecimalField(max_digits=4, decimal_places=2, default=0.30)
    weight_order = models.DecimalField(max_digits=4, decimal_places=2, default=0.20)

    cap_worst = models.DecimalField(**percent(default=10))
    cap_blended = models.DecimalField(**percent(default=5))
    cap_order = models.DecimalField(**percent(default=5))

    high_band_threshold = models.DecimalField(**percent(default=60))

    class Meta:
        db_table = "risk_config"

    @classmethod
    def get_solo(cls) -> "RiskConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
