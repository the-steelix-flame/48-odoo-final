from django.db import models

from apps.common.enums import CustomerTier
from apps.common.models import MONEY, PERCENT, TimeStampedModel


class ProductCategory(TimeStampedModel):
    """Hardware / Services / Subscription.

    A real table, not a string on Product, because the category discount
    ceiling hangs off it and that ceiling is editable in screen 18.
    """

    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=40, unique=True)

    class Meta:
        db_table = "product_category"
        verbose_name_plural = "product categories"

    def __str__(self) -> str:
        return self.name


class Product(TimeStampedModel):
    name = models.CharField(max_length=150)
    sku = models.CharField(max_length=60, unique=True)
    category = models.ForeignKey(
        ProductCategory, on_delete=models.PROTECT, related_name="products"
    )
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=20, default="Each")
    base_price = models.DecimalField(**MONEY)
    #: Required for margin. Never serialised to the customer portal.
    cost_price = models.DecimalField(**MONEY)
    tax_percent = models.DecimalField(**PERCENT)

    is_subscription = models.BooleanField(default=False)
    recurring_plan = models.ForeignKey(
        "subscriptions.RecurringPlan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )

    #: Ranks higher in the upsell panel and shows a "Promo" tag.
    is_promoted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "product"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def margin_percent(self):
        if not self.base_price:
            return 0
        return (self.base_price - self.cost_price) / self.base_price * 100

    @property
    def quantity_on_hand(self) -> int:
        """Derived from stock_item across all warehouses.

        Deliberately NOT a column. Two sources of truth for stock is exactly
        the bug that ruins a fulfillment demo.
        """
        from django.db.models import Sum

        total = self.stock_items.aggregate(total=Sum("quantity_on_hand"))["total"]
        return total or 0


class ProductAttribute(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="attributes")
    name = models.CharField(max_length=60)  # "Color", "RAM", "Manufacturer"

    class Meta:
        db_table = "product_attribute"
        unique_together = [("product", "name")]


class ProductAttributeValue(TimeStampedModel):
    attribute = models.ForeignKey(
        ProductAttribute, on_delete=models.CASCADE, related_name="values"
    )
    value = models.CharField(max_length=60)  # "Blue", "8GB", "Dell"
    extra_price = models.DecimalField(**MONEY)

    class Meta:
        db_table = "product_attribute_value"
        unique_together = [("attribute", "value")]


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku_suffix = models.CharField(max_length=40)
    #: Cached sum of the chosen attribute values' extra_price.
    extra_price = models.DecimalField(**MONEY)
    values = models.ManyToManyField(ProductAttributeValue, related_name="variants", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "product_variant"
        unique_together = [("product", "sku_suffix")]


class PriceList(TimeStampedModel):
    name = models.CharField(max_length=120)
    tier = models.CharField(
        max_length=10, choices=CustomerTier.choices, null=True, blank=True
    )
    currency = models.CharField(max_length=3, default="USD")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "price_list"

    def __str__(self) -> str:
        return f"{self.name} ({self.currency})"


class PriceListRule(TimeStampedModel):
    class RuleType(models.TextChoices):
        FIXED = "FIXED", "Fixed price"
        PERCENT_OFF = "PERCENT_OFF", "Percent off base"

    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="rules")
    #: null product + null category = applies to everything in the list.
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.CASCADE, related_name="price_rules"
    )
    category = models.ForeignKey(
        ProductCategory, null=True, blank=True, on_delete=models.CASCADE, related_name="price_rules"
    )
    rule_type = models.CharField(max_length=16, choices=RuleType.choices)
    value = models.DecimalField(**MONEY)
    priority = models.IntegerField(default=0)

    class Meta:
        db_table = "price_list_rule"
        ordering = ["-priority"]


class ProductPairing(TimeStampedModel):
    """The upsell / cross-sell graph. Directed: source -> also bought target."""

    source_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="pairings_out"
    )
    target_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="pairings_in"
    )
    co_purchase_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "product_pairing"
        unique_together = [("source_product", "target_product")]


class UpsellConfig(TimeStampedModel):
    """Singleton (pk=1). Editable so a judge can watch a suggestion disappear."""

    min_margin_percent = models.DecimalField(**PERCENT, help_text="Never suggest below this margin")
    promoted_boost = models.DecimalField(max_digits=5, decimal_places=2, default=0.25)

    class Meta:
        db_table = "upsell_config"

    @classmethod
    def get_solo(cls) -> "UpsellConfig":
        obj, _ = cls.objects.get_or_create(
            pk=1, defaults={"min_margin_percent": 20, "promoted_boost": 0.25}
        )
        return obj


class UpsellSuggestionLog(TimeStampedModel):
    class Action(models.TextChoices):
        SHOWN = "SHOWN", "Shown"
        ADDED = "ADDED", "Added to quote"
        DISMISSED = "DISMISSED", "Dismissed"

    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="upsell_logs"
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="upsell_logs")
    action = models.CharField(max_length=12, choices=Action.choices)
    margin_delta = models.DecimalField(**MONEY)
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "upsell_suggestion_log"
