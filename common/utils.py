from dataclasses import dataclass

from django.http import QueryDict
from django.utils.http import url_has_allowed_host_and_scheme

from coins.exceptions import CoinGeckoAuthError, CoinGeckoResponseError

VALID_DIRECTIONS = {"asc", "desc"}
REQUEST_ALLOWED_SORTS_ATTR = "_common_allowed_sorts"


class InvalidQueryState(ValueError):
    pass


@dataclass(frozen=True)
class QueryState:
    page: int
    sort: str
    direction: str

    def as_tuple(self):
        return self.page, self.sort, self.direction


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


def build_query_string(params):
    query = QueryDict(mutable=True)
    for key, value in params.items():
        if value is None:
            continue
        query[key] = str(value)
    return query.urlencode()


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


def _normalize_page(request, page_count):
    raw_page = request.GET.get("page")
    if raw_page is None or not raw_page.strip():
        page = 1
    else:
        try:
            page = int(raw_page.strip())
        except ValueError as exc:
            raise InvalidQueryState("page must be an integer") from exc
        if page < 1:
            raise InvalidQueryState("page must be greater than zero")

    if page_count is None:
        return page

    page_count = max(int(page_count or 1), 1)
    return min(page_count, page)


def _normalize_sort_direction(request, allowed_sorts, default_sort, default_direction):
    if default_direction not in VALID_DIRECTIONS:
        raise ValueError("default_direction must be 'asc' or 'desc'")

    if allowed_sorts is not None and default_sort not in allowed_sorts:
        raise ValueError("default_sort must be present in allowed_sorts")

    raw_sort = request.GET.get("sort")
    raw_direction = request.GET.get("direction")
    sort = raw_sort.strip() if raw_sort is not None else ""
    direction = raw_direction.strip() if raw_direction is not None else ""

    if not sort and not direction:
        return default_sort, default_direction

    if not sort or not direction:
        raise InvalidQueryState("sort and direction must be supplied together")

    if allowed_sorts is not None and sort not in allowed_sorts:
        raise InvalidQueryState("sort is not allowed")

    if direction not in VALID_DIRECTIONS:
        raise InvalidQueryState("direction must be 'asc' or 'desc'")

    return sort, direction


def normalize_query_state(
    request,
    *,
    allowed_sorts,
    default_sort,
    default_direction,
    page_count=None,
):
    page = _normalize_page(request, page_count)
    sort, direction = _normalize_sort_direction(
        request, allowed_sorts, default_sort, default_direction
    )
    return QueryState(page=page, sort=sort, direction=direction)


def get_common_params(default_sort, default_direction, allowed_sorts=None):
    def func(request, page_count):
        state = normalize_query_state(
            request,
            allowed_sorts=allowed_sorts
            if allowed_sorts is not None
            else getattr(request, REQUEST_ALLOWED_SORTS_ATTR, None),
            default_sort=default_sort,
            default_direction=default_direction,
            page_count=page_count,
        )
        return state.as_tuple()

    return func
