from django.contrib import admin

from apps.accounts.models import Customer, SalesTeam, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "role", "sales_team", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("email", "full_name")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "tier", "currency", "owner_rep")
    list_filter = ("tier",)
    search_fields = ("name",)


admin.site.register(SalesTeam)
