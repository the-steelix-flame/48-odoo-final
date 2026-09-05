from django.contrib import admin

from apps.fulfillment.models import (
    FulfillmentAllocation,
    FulfillmentPlan,
    StockItem,
    StockMove,
    Warehouse,
)


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse", "quantity_on_hand", "quantity_reserved", "available")
    list_filter = ("warehouse",)


admin.site.register([Warehouse, StockMove, FulfillmentPlan, FulfillmentAllocation])
