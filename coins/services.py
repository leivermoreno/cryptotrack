from django.conf import settings
import requests
import threading


API_KEY = settings.COINGECKO_KEY
ENDPOINT = settings.COINGECKO_ENDPOINT

_thread_local = threading.local()


def _get_session():
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        session.headers.update({"x-cg-demo-api-key": API_KEY})
        _thread_local.session = session

    return _thread_local.session


def get_coin_list_with_data():
    res = _get_session().get(
        ENDPOINT + "coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "page": "1",
            "per_page": 100,
            "price_change_percentage": "24h,7d",
        },
    )

    return res.json()
