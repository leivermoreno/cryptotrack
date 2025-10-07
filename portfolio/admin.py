from django.contrib import admin

from portfolio.models import PortfolioTransaction


@admin.register(PortfolioTransaction)
class PortfolioTransactionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "coin__name", "type", "amount", "price", "created")
    list_filter = ("type", "created")
    search_fields = ("user__username", "coin__name")
    ordering = ("-created",)
    fieldsets = (
        (None, {"fields": ("user", "coin", "type", "amount", "price", "created")}),
    )

    def has_change_permission(self, request, obj=None):
        return False
