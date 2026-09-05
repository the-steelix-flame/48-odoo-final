from django.contrib import admin

from apps.subscriptions.models import RecurringPlan, Subscription, SubscriptionEvent


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("customer", "plan", "quantity", "status", "next_bill_date")
    list_filter = ("status", "plan")


admin.site.register([RecurringPlan, SubscriptionEvent])
