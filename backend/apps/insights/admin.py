from django.contrib import admin

from apps.insights.models import AlertAction, DealAlert, DealHealthConfig, RepDiscountStat


@admin.register(DealAlert)
class DealAlertAdmin(admin.ModelAdmin):
    list_display = ("quotation", "alert_type", "severity", "message", "status", "detected_at")
    list_filter = ("alert_type", "severity", "status")


admin.site.register([DealHealthConfig, RepDiscountStat, AlertAction])
