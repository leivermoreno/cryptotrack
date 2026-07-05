from django.utils.http import url_has_allowed_host_and_scheme

from coins.exceptions import CoinGeckoAuthError, CoinGeckoResponseError


def log_coingecko_failure(logger, exc):
    """Log a ``CoinGeckoError`` at a severity tiered by its subclass.

    Auth/response failures signal a broken key or a changed API contract and are
    logged at ERROR; transport/server/rate-limit failures are transient and
    logged at WARNING with a traceback. Shared by every catch site (views and
    the scheduler). Richer logging is step 13.6.
    """
    if isinstance(exc, (CoinGeckoAuthError, CoinGeckoResponseError)):
        logger.error("CoinGecko request failed: %s", exc)
    else:
        logger.warning("CoinGecko request failed: %s", exc, exc_info=exc)


def handle_market_unavailable(logger, exc):
    """Log a ``CoinGeckoError`` and return the degraded-context fragment.

    Views catch ``CoinGeckoError`` around their market-data calls and merge the
    returned dict into the template context to render an in-place "market data
    unavailable" banner with an empty table (HTTP 200 — the page shell stays
    usable).
    """
    log_coingecko_failure(logger, exc)
    return {"coin_list": [], "market_unavailable": True}


def add_direction_sign(sort, direction):
    if direction == "desc":
        return f"-{sort}"
    return sort


def get_safe_redirect_url(request, redirect_to):
    if redirect_to is None:
        return None

    redirect_to = redirect_to.strip()
    if not redirect_to:
        return None

    if url_has_allowed_host_and_scheme(
        url=redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect_to
    return None


def get_common_params(default_sort, default_direction):
    def func(request, page_count):
        page_count = page_count or 1
        page = int(request.GET.get("page", "1"))
        page = min(page_count, page)
        sort = request.GET.get("sort", default_sort)
        direction = request.GET.get("direction", default_direction)

        return page, sort, direction

    return func
