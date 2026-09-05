from django.contrib import admin

from apps.approvals.models import ApprovalRequest, ApprovalStep


class StepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 0


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ("quotation", "risk_band", "risk_score", "status", "created_at")
    list_filter = ("status", "risk_band")
    inlines = [StepInline]
