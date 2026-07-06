from django.contrib import admin

from portfolio.models import PortfolioTransaction


@admin.register(PortfolioTransaction)
class PortfolioTransactionAdmin(admin.ModelAdmin):
    # Read-only audit log (step 13.4): the admin bypasses portfolio.ledger,
    # which enforces the ledger invariants (oversell/FIFO feasibility,
    # delisted-buy guard), so admin add/change/delete are all disabled to avoid
    # corrupting the ledger. Users get enforced create/edit/delete through the
    # app, not here.
    list_display = (
        "id",
        "user",
        "coin__name",
        "type",
        "amount",
        "price",
        "trade_date",
        "created",
    )
    list_filter = ("type", "trade_date", "created")
    search_fields = ("user__username", "coin__name")
    autocomplete_fields = ("user", "coin")
    ordering = ("-created",)
    # `created` (auto_now_add) is the non-editable insert timestamp, so it must
    # be read-only; `trade_date` is the editable user-entered trade date.
    readonly_fields = ("created",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "coin",
                    "type",
                    "amount",
                    "price",
                    "trade_date",
                    "created",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
