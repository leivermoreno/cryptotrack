import threading
import math

from django.conf import settings
from django.core.cache import cache
import requests


CG_API_KEY = settings.COINGECKO_KEY
CG_URL = settings.COINGECKO_ENDPOINT
RESULTS_PAGE = 100
COIN_COUNT_TIMEOUT = settings.CACHE_TIMEOUT_COIN_COUNT
PAGE_DATA_TIMEOUT = settings.CACHE_TIMEOUT_PAGE_DATA
ALLOWED_SORTS = {
    "rank": "market_cap_rank",
    "coin": "name",
    "price": "current_price",
    "price_change_24h": "price_change_percentage_24h_in_currency",
    "price_change_7d": "price_change_percentage_7d_in_currency",
    "ath": "ath",
    "volume": "total_volume",
    "market_cap": "market_cap",
}
ALLOWED_DIRECTIONS = ["asc", "desc"]

_thread_local = threading.local()


def _get_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({"x-cg-demo-api-key": CG_API_KEY})
        _thread_local.session = session

    return _thread_local.session


def get_coin_list():

    res = _get_session().get(
        CG_URL + "coins/list",
        params={"status": "active"},
    )

    return res


def get_coin_count():
    return cache.get_or_set(
        "coin_count", len(get_coin_list().json()), COIN_COUNT_TIMEOUT
    )


def get_page_count():
    return math.ceil(get_coin_count() / RESULTS_PAGE)


def get_coin_list_with_data(page, sort, direction):
    if cache.has_key(f"coin_list_page_{page}"):
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
                    "per_page": 100,
                    "price_change_percentage": "24h,7d",
                },
            )
            .json()
        )
        cache.set(f"coin_list_page_{page}", data, PAGE_DATA_TIMEOUT)

    return _sort_coin_list(data, sort, direction)


def _sort_coin_list(data, sort, direction):
    if sort == "rank" and direction == "asc":
        return data

    reverse = direction == "desc"
    key = ALLOWED_SORTS[sort]
    data.sort(key=lambda x: x.get(key) or 0, reverse=reverse)

    return data
