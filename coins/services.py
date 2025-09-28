import threading
import math
from django.conf import settings
from django.core.cache import cache
import requests
from coins.settings import ALLOWED_SORTS, RESULTS_PAGE

CG_API_KEY = settings.COINGECKO_KEY
CG_URL = settings.COINGECKO_ENDPOINT
SUPPORTED_COINS_TIMEOUT = settings.CACHE_SUPPORTED_COINS_TIMEOUT
PAGE_DATA_TIMEOUT = settings.CACHE_INDEX_TABLE_DATA_TIMEOUT

_thread_local = threading.local()


def _get_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({"x-cg-demo-api-key": CG_API_KEY})
        _thread_local.session = session

    return _thread_local.session


def get_supported_coin_list():
    if cache.has_key("supported_coin_list"):
        return cache.get("supported_coin_list")
    else:
        res = _get_session().get(
            CG_URL + "coins/list",
            params={"status": "active"},
        )

        data = res.json()
        cache.set("supported_coin_list", data, SUPPORTED_COINS_TIMEOUT)

        return res.json()


def get_coin_count():
    return len(get_supported_coin_list())


def get_page_count():
    return math.ceil(get_coin_count() / RESULTS_PAGE)


# todo remove if not needed
# def get_simple_coin_data(coin_id):
#     try:
#         coin = Coin.objects.get(cg_id=coin_id)
#     except Coin.DoesNotExist:
#         res = _get_session().get(
#             CG_URL + f"coins/{coin_id}",
#         )
#
#         if res.status_code == 404:
#             return None
#
#         coin_data = res.json()
#         coin = Coin.objects.create(
#             cg_id=coin_data["id"],
#             name=coin_data["name"],
#             symbol=coin_data["symbol"],
#         )
#
#     return coin


def get_coin_list_with_market(page, sort, direction, ids=None):
    # not caching when ids are provided because that would create too many cache entries
    if ids is not None and len(ids) == 0:
        return []

    if ids is None and cache.has_key(f"coin_list_page_{page}"):
        data = cache.get(f"coin_list_page_{page}")
    else:
        data = (
            _get_session()
            .get(
                CG_URL + "coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "page": page,
                    "per_page": RESULTS_PAGE,
                    "price_change_percentage": "24h,7d",
                    "ids": ",".join(ids) if ids else "",
                },
            )
            .json()
        )
        if ids is None:
            cache.set(f"coin_list_page_{page}", data, PAGE_DATA_TIMEOUT)

    return _sort_coin_list(data, sort, direction)


def _sort_coin_list(data, sort, direction):
    if sort == "rank" and direction == "asc":
        return data

    reverse = direction == "desc"
    key = ALLOWED_SORTS[sort]
    data.sort(key=lambda x: x.get(key) or 0, reverse=reverse)

    return data
