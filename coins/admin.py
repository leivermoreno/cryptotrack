from django.contrib import admin

from coins.models import Coin


@admin.register(Coin)
class CoinAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "symbol", "is_active")
    search_fields = ("name", "symbol")
    ordering = ("id",)
    fieldsets = ((None, {"fields": ("name", "symbol", "is_active")}),)
    readonly_fields = (
        "name",
        "symbol",
    )
