from django.contrib import admin

from coins.models import Coin, Watchlist


# Read-only mirror of the CoinGecko catalog (rebuilt by sync_supported_coins);
# only is_active is human-editable. cg_id is shown for support but read-only --
# editing it would orphan Watchlist/PortfolioTransaction rows.
@admin.register(Coin)
class CoinAdmin(admin.ModelAdmin):
    list_display = ("id", "cg_id", "name", "symbol", "is_active")
    search_fields = ("cg_id", "name", "symbol")
    ordering = ("id",)
    fieldsets = ((None, {"fields": ("cg_id", "name", "symbol", "is_active")}),)
    readonly_fields = ("cg_id", "name", "symbol")

    def has_add_permission(self, request):
        return False


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "coin__name", "coin__symbol", "created")
    list_filter = ("created", "coin__is_active")
    search_fields = ("user__username", "coin__name", "coin__symbol")
    ordering = ("-created",)
    autocomplete_fields = ("user", "coin")
    readonly_fields = ("created",)
    fieldsets = ((None, {"fields": ("user", "coin", "created")}),)
