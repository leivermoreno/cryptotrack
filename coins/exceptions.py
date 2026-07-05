"""Structured errors raised by the CoinGecko client boundary.

Consumers (views, portfolio services, scheduler) should catch ``CoinGeckoError``
(the base) to handle any failure uniformly; the subclasses let callers and
logging distinguish "retry later" (unavailable/server/rate-limit) from "config
broken" (auth) from "bad data" (response). No ``requests.*`` exception escapes
the client -- every failure is wrapped in one of these (``raise ... from exc``).

Kept in a dedicated module (not ``coins/services.py``) so consumers can import
the catch targets without pulling in the HTTP module.
"""


class CoinGeckoError(Exception):
    """Base class for every error raised by the CoinGecko client."""


class CoinGeckoUnavailableError(CoinGeckoError):
    """Transport-level failure: timeout, connection error, DNS, etc."""


class CoinGeckoServerError(CoinGeckoUnavailableError):
    """CoinGecko returned a 5xx status."""


class CoinGeckoRateLimitError(CoinGeckoError):
    """CoinGecko returned HTTP 429. Carries ``retry_after`` when provided."""

    def __init__(self, *args, retry_after=None):
        super().__init__(*args)
        self.retry_after = retry_after


class CoinGeckoAuthError(CoinGeckoError):
    """CoinGecko returned 401/403 (missing or invalid API key)."""


class CoinGeckoResponseError(CoinGeckoError):
    """Malformed or unexpected response: bad JSON, wrong shape, other 4xx."""
