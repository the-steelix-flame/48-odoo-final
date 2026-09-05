from django.contrib import admin

from apps.quotations.models import Quotation, QuotationEvent, QuotationLine


class QuotationLineInline(admin.TabularInline):
    model = QuotationLine
    extra = 0


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "status", "total", "risk_band", "requires_approval")
    list_filter = ("status", "risk_band")
    search_fields = ("number", "customer__name")
    inlines = [QuotationLineInline]


admin.site.register(QuotationEvent)
