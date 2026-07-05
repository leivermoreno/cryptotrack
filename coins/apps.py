from django.apps import AppConfig
from django.core.checks import Warning, register


class CoinsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "coins"

    def ready(self):
        register(check_coingecko_key)


def check_coingecko_key(app_configs, **kwargs):
    from django.conf import settings

    if not settings.COINGECKO_KEY:
        return [
            Warning(
                "CRYPTO_COINGECKO_KEY is not set; CoinGecko requests will fail.",
                hint="Set CRYPTO_COINGECKO_KEY in your .env or environment. "
                "Market data, search, watchlist, portfolio overview, and the "
                "catalog sync all require it.",
                id="coins.W001",
            )
        ]
    return []
