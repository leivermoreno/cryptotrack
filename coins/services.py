import threading
import math

from django.conf import settings
import requests


CG_API_KEY = settings.COINGECKO_KEY
CG_URL = settings.COINGECKO_ENDPOINT
RESULTS_PAGE = 100

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
    return len(get_coin_list().json())


def get_page_count():
    return math.ceil(get_coin_count() / RESULTS_PAGE)


def get_coin_list_with_data(page):
    res = _get_session().get(
        CG_URL + "coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "page": page,
            "per_page": 100,
            "price_change_percentage": "24h,7d",
        },
    )

    return res.json()
