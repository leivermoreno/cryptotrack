from dataclasses import dataclass

from coins.models import Coin
from coins.services import get_supported_coin_list


@dataclass(frozen=True)
class SupportedCoinSyncResult:
    created: int = 0
    updated: int = 0
    deactivated: int = 0
    skipped: int = 0
    failed: int = 0


def log_sync_result(logger, result):
    logger.info(
        "CoinGecko supported coin sync completed: "
        "created=%s updated=%s deactivated=%s skipped=%s failed=%s",
        result.created,
        result.updated,
        result.deactivated,
        result.skipped,
        result.failed,
    )


def _is_blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def sync_supported_coins():
    """Fetch CoinGecko's active catalog and mirror local active flags."""
    coin_list = get_supported_coin_list()
    coin_catalog = {}
    failed = 0
    for coin in coin_list:
        try:
            cg_id = coin["id"]
            name = coin["name"]
            symbol = coin["symbol"]
        except (KeyError, TypeError):
            failed += 1
            continue

        if _is_blank(cg_id) or _is_blank(name) or _is_blank(symbol):
            failed += 1
            continue

        try:
            coin_catalog[cg_id] = {"name": name, "symbol": symbol}
        except TypeError:
            failed += 1

    existing_coins = Coin.objects.in_bulk(coin_catalog, field_name="cg_id")

    coins_to_create = []
    coins_to_update = []
    skipped = 0

    for cg_id, coin_data in coin_catalog.items():
        coin = existing_coins.get(cg_id)
        if coin is None:
            coins_to_create.append(Coin(cg_id=cg_id, is_active=True, **coin_data))
            continue

        if (
            coin.name == coin_data["name"]
            and coin.symbol == coin_data["symbol"]
            and coin.is_active
        ):
            skipped += 1
            continue

        coin.name = coin_data["name"]
        coin.symbol = coin_data["symbol"]
        coin.is_active = True
        coins_to_update.append(coin)

    if coins_to_create:
        Coin.objects.bulk_create(coins_to_create, ignore_conflicts=True)
    if coins_to_update:
        Coin.objects.bulk_update(coins_to_update, ["name", "symbol", "is_active"])

    deactivated = (
        Coin.objects.filter(is_active=True)
        .exclude(cg_id__in=coin_catalog)
        .update(is_active=False)
    )

    return SupportedCoinSyncResult(
        created=len(coins_to_create),
        updated=len(coins_to_update),
        deactivated=deactivated,
        skipped=skipped,
        failed=failed,
    )
