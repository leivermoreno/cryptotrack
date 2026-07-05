import math
import threading

import requests
from django.conf import settings
from django.core.cache import cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from coins.exceptions import (
    CoinGeckoAuthError,
    CoinGeckoRateLimitError,
    CoinGeckoResponseError,
    CoinGeckoServerError,
    CoinGeckoUnavailableError,
)
from coins.settings import ALLOWED_SORTS, RESULTS_PAGE

CG_API_KEY = settings.COINGECKO_KEY
CG_URL = settings.COINGECKO_ENDPOINT
SUPPORTED_COINS_TIMEOUT = settings.CACHE_SUPPORTED_COINS_TIMEOUT_SECONDS
PAGE_DATA_TIMEOUT = settings.CACHE_MARKET_PAGE_TIMEOUT_SECONDS

# Distinct cache-miss sentinel: a legitimately cached empty market page must be
# distinguishable from an absent key, so `None` cannot serve as the default.
_MISS = object()

# Cache-key namespace/version. Bump when the cached payload SHAPE changes so a
# deploy never serves stale pre-deploy pickles (the DB-backed `cache` table
# survives deploys; 60s/2h timeouts only bound, not eliminate, the window).
CACHE_VERSION = "v1"
SUPPORTED_COINS_KEY = f"{CACHE_VERSION}:supported_coin_list"

# (connect, read) timeouts in seconds. Hardcoded operational tuning, injectable
# per-instance via the client constructor for tests.
CONNECT_TIMEOUT = 3.05
READ_TIMEOUT = 10.0

# Conservative retry policy on idempotent GETs. Uses urllib3 (already a
# transitive dep via requests); no new dependency.
_RETRY = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
)


class CoinGeckoClient:
    """CoinGecko HTTP client with a DB-backed (`DatabaseCache`) cache contract:

    - Supported coin list: cached ~2h under ``v1:supported_coin_list``.
    - Market pages (``ids is None``): cached ~60s under
      ``v1:coin_list_page_{page}``, keyed by page only. CoinGecko is always
      queried ``market_cap_desc``/USD and sort/direction are applied *after* the
      cache read, so they are deliberately not part of the key.
    - Id-specific market data (``ids`` given, from search/watchlist/portfolio):
      NOT cached — the id sets are arbitrary, already-paginated user input, so
      caching them would grow the cache table without bound.

    Keys carry a ``v1:`` version prefix so a payload-shape change can invalidate
    stale pre-deploy pickles by bumping ``CACHE_VERSION``.
    """

    def __init__(
        self,
        api_key=CG_API_KEY,
        base_url=CG_URL,
        supported_coins_timeout=SUPPORTED_COINS_TIMEOUT,
        page_data_timeout=PAGE_DATA_TIMEOUT,
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
        session=None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.supported_coins_timeout = supported_coins_timeout
        self.page_data_timeout = page_data_timeout
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._thread_local = threading.local()
        # Test seam: an injected session bypasses the thread-local/adapter setup
        # so unit tests can drive the real client logic against canned responses.
        # Default None keeps production behavior byte-identical.
        self._session_override = session

    def _session(self):
        if self._session_override is not None:
            return self._session_override

        if not hasattr(self._thread_local, "session"):
            session = requests.Session()
            session.headers.update({"x-cg-demo-api-key": self.api_key})
            adapter = HTTPAdapter(max_retries=_RETRY)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._thread_local.session = session

        return self._thread_local.session

    def _request(self, path, params):
        """GET ``path`` and return decoded JSON, or raise a CoinGeckoError.

        Wraps every transport/status/decode failure so no ``requests.*``
        exception escapes the client.
        """
        try:
            res = self._session().get(
                self.base_url + path,
                params=params,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.RequestException as exc:
            raise CoinGeckoUnavailableError(
                f"CoinGecko request to {path} failed"
            ) from exc

        status = res.status_code
        if status == 429:
            raise CoinGeckoRateLimitError(
                "CoinGecko rate limit exceeded",
                retry_after=res.headers.get("Retry-After"),
            )
        if status in (401, 403):
            raise CoinGeckoAuthError(
                f"CoinGecko rejected the API key (HTTP {status}); check COINGECKO_KEY"
            )
        if status >= 500:
            raise CoinGeckoServerError(f"CoinGecko server error (HTTP {status})")

        try:
            res.raise_for_status()
        except requests.HTTPError as exc:
            raise CoinGeckoResponseError(
                f"CoinGecko returned HTTP {status} for {path}"
            ) from exc

        try:
            return res.json()
        except ValueError as exc:
            raise CoinGeckoResponseError(
                f"CoinGecko returned malformed JSON for {path}"
            ) from exc

    def list_supported_coins(self):
        data = cache.get(SUPPORTED_COINS_KEY, _MISS)
        if data is not _MISS:
            return data

        data = self._request("coins/list", {"status": "active"})

        # Validate shape before caching so bad/empty responses are never cached.
        if not isinstance(data, list) or not data:
            raise CoinGeckoResponseError(
                "CoinGecko supported-coin list was empty or not a list"
            )

        cache.set(SUPPORTED_COINS_KEY, data, self.supported_coins_timeout)
        return data

    def get_coin_count(self):
        return len(self.list_supported_coins())

    def get_page_count(self):
        return math.ceil(self.get_coin_count() / RESULTS_PAGE)

    def get_markets(self, page, sort, direction, ids=None):
        # Id-specific requests (search/watchlist/portfolio) are NOT cached: the id
        # sets come from arbitrary, already-paginated user input, so their key
        # space is unbounded and the DB-backed cache table has no LRU eviction.
        if ids is not None:
            if len(ids) == 0:
                return []
            data = self._fetch_markets(page, ids)
            return self._sort(data, sort, direction)

        # ids is None: cacheable market page, keyed by page only. CoinGecko is
        # always queried market_cap_desc with vs_currency=usd (both hardcoded in
        # _fetch_markets), and sort/direction are applied post-cache by _sort, so
        # they must not be part of the key.
        key = f"{CACHE_VERSION}:coin_list_page_{page}"
        data = cache.get(key, _MISS)
        if data is _MISS:
            data = self._fetch_markets(page, ids=None)
            cache.set(key, data, self.page_data_timeout)

        return self._sort(data, sort, direction)

    def _fetch_markets(self, page, ids):
        data = self._request(
            "coins/markets",
            {
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "page": page,
                "per_page": RESULTS_PAGE,
                "price_change_percentage": "24h,7d",
                "ids": ",".join(ids) if ids else "",
            },
        )
        # Validate shape before caching/sorting (an empty list is valid for
        # unknown ids; a non-list would break _sort and must never cache).
        if not isinstance(data, list):
            raise CoinGeckoResponseError("CoinGecko market data was not a list")
        return data

    @staticmethod
    def _sort(data, sort, direction):
        if sort == "rank" and direction == "asc":
            return data

        reverse = direction == "desc"
        key = ALLOWED_SORTS[sort]
        # Return a new list rather than sorting in place: `data` may be a value
        # handed back from the cache, and callers must not observe mutation.
        return sorted(data, key=lambda x: x.get(key) or 0, reverse=reverse)


_default_client = CoinGeckoClient()


def get_supported_coin_list():
    return _default_client.list_supported_coins()


def get_coin_count():
    return _default_client.get_coin_count()


def get_page_count():
    return _default_client.get_page_count()


def get_coin_list_with_market(page, sort, direction, ids=None):
    return _default_client.get_markets(page, sort, direction, ids=ids)
