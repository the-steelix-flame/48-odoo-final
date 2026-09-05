from django.contrib import admin

from apps.billing.models import CreditNote, Invoice, InvoiceLine, Payment


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "customer", "invoice_type", "status", "total", "amount_paid")
    list_filter = ("status", "invoice_type")
    inlines = [InvoiceLineInline]


admin.site.register([Payment, CreditNote])
