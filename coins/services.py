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


def get_coin_list_with_data(page):
    if cache.has_key(f"coin_list_page_{page}"):
        return cache.get(f"coin_list_page_{page}")
    else:
        res = (
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
        cache.set(f"coin_list_page_{page}", res, PAGE_DATA_TIMEOUT)

        return res
