from django.contrib import admin

from apps.catalog.models import (
    PriceList,
    PriceListRule,
    Product,
    ProductCategory,
    ProductPairing,
    ProductVariant,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "sku", "category", "base_price", "cost_price", "is_subscription")
    list_filter = ("category", "is_subscription", "is_promoted", "is_active")
    search_fields = ("name", "sku")


admin.site.register([ProductCategory, ProductVariant, PriceList, PriceListRule, ProductPairing])
