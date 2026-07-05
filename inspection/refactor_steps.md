# CryptoTrack Refactor Steps

This plan combines the findings from:

- `inspection/README.md`
- `inspection/settings.md`
- `inspection/common.md`
- `inspection/coins.md`
- `inspection/portfolio.md`
- `inspection/accounts.md`

The ordering is intentional. First make the project runnable and testable, then
remove cross-cutting hazards, then refactor domain logic, and only then polish UI
and deployment details.

Subtasks are numbered `N.M` (e.g. `1.1`) for easy reference. Completed items are
marked ✅.

## Ordered Refactor Plan

1. **Make local development and tests reproducible**

   Goal: make every later change verifiable without hidden environment or network
   dependencies.

   - 1.1 ✅ Add `.env.example` with required and optional variables.
   - 1.2 ✅ Stop requiring `CRYPTO_COINGECKO_KEY` at Django settings import time.
   - 1.3 ✅ Centralize environment-variable access behind a small helper
     (`env`, `env_bool`, `env_list`) — no new dependency (Option A). Route the
     existing vars through it so that: required vars fail with a clear
     `ImproperlyConfigured` message instead of a raw `KeyError`; optional vars
     have explicit defaults; and `.strip()` plus bool/int/csv coercion live in
     one place. This lays the helper only — section 3 tightens the actual
     policies (3.2 real secret outside dev, 3.3 safe `CSRF_TRUSTED_ORIGINS`
     parse, 3.5 fail-closed debug parser, 3.6 unit-named timeouts) on top of it.
     Note: settings constants that don't vary per environment (e.g. `LOGIN_URL`
     in 1.4) stay hardcoded — the helper is for env-driven config only.
   - 1.4 ✅ Add explicit `LOGIN_URL`, `LOGIN_REDIRECT_URL`, and `LOGOUT_REDIRECT_URL`.
   - 1.5 ✅ Decide and document whether local/test uses PostgreSQL only or a lightweight
     test settings path. Decision: **PostgreSQL only** (dev, test, and production) —
     no SQLite fallback or separate test settings, to avoid engine divergence in
     financial/`Decimal` logic. Documented in `README.md` ("Database Strategy").
   - 1.6 ✅ Add `STATIC_ROOT` and clarify the current static-file strategy.
     Decision: serve the small hand-maintained asset set (`style.css` + admin)
     from the app process via **WhiteNoise** (no CDN/reverse proxy). Added
     `STATIC_ROOT`, `STORAGES` with `CompressedManifestStaticFilesStorage`, and
     the WhiteNoise middleware after `SecurityMiddleware`. Documented in
     `README.md` ("Static Files"). Deployment specifics (prod server, process
     topology) remain in step 16.
   - 1.7 ✅ Add a short setup verification path such as `manage.py check`, migrations,
     cache table creation, and tests. Added `scripts/verify_setup.sh`, which runs
     `check` → `migrate` → `createcachetable` → `test` in order (idempotent,
     stops at first failure, uses `venv/bin/python`). Documented in `README.md`
     ("Verifying Your Setup").

   Verification:

   - `scripts/verify_setup.sh` (runs `check` and the full test suite; the
     CoinGecko key is no longer required at import after 1.2, so no
     `COINGECKO_KEY=dummy` prefix is needed)

2. **Establish a safety-net test baseline**

   Goal: capture current intended behavior before changing shared helpers or
   business rules.

   Conventions for this section (decided up front, applied to every subtask):
   - **Known bugs use `@unittest.expectedFailure`** — the test asserts the
     *correct* desired behavior and is marked expected-failure, with a comment
     citing the inspection doc and the later step that fixes it. The suite stays
     green now (expected failures don't fail the run); when the bug is fixed the
     test flips to an "unexpected success" (XPASS), which signals the fix landed
     and the marker should be removed.
   - **Tests only** — no application code is changed in section 2. If a behavior
     can't be tested without a code change, it's left for the owning step.
   - **CoinGecko is mocked at the service-function seam** (`get_coin_list_with_market`,
     `get_page_count`) patched *where they're imported* (`coins.views.*`,
     `portfolio.services.*`), via a shared factory in `common/test_utils.py`
     (`make_market_coin` / `market_response`). Numeric market fields are floats,
     matching CoinGecko's JSON (strings break the `format_number` filter and are
     unnecessary for `Decimal`). The whole suite now runs offline.
   - Undecided **design decisions** (e.g. whether a 0% change is neutral) are
     characterized as green against current behavior, not marked expected-failure.

   - 2.1 ✅ Mock CoinGecko in all view tests that currently touch market data.
     Added `common/test_utils.py` (shared market-payload factory, documents the
     patch targets) and converted the network-hitting `coins`/`portfolio` view
     tests to patch `get_coin_list_with_market`/`get_page_count`. Suite runs
     fully offline; no app code changed.
   - 2.2 ✅ Add direct tests for `accounts` login, logout, registration, and redirects.
     12 green tests over login (render, valid/invalid, `next`, authed-redirect),
     register (render, valid create → redirect to login with no auto-login,
     invalid, authed-redirect), logout, and navbar auth states. Asserts against
     `settings.LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL` (not hardcoded `/`); uses
     `get_user_model()` per the step-9 direction. No genuine current bug found, so
     no expected-failure tests; deferred enhancements (auto-login, success
     messages, password reset) are left for step 14.
   - 2.3 ✅ Add direct tests for `common` query validation, pagination, formatting, and
     sort-link generation. 52 tests, 8 marked `@expectedFailure` for known bugs:
     negative non-integer `format_number`/`format_amount` truncation (→ step 8.1),
     `format_number("")` raising instead of a safe fallback (→ 8.2), `-0.00%` from
     tiny negatives in `format_percentage` (→ 8.3), and `sort_link` not
     URL-encoding the `search` value (→ 7.3/7.4). Decorator/`get_common_params`
     validation, page clamping, and the pagination partial (incl. its hard-coded
     "Back to Market" link) are characterized green; `percentage_change_class(0)`
     kept green pending the step-8.4 neutral-vs-danger decision.
   - 2.4 ✅ Add `coins` tests for watchlist toggling, invalid CoinGecko ids, inactive
     coins, query preservation, and unsafe `next` values. Added green tests for
     fresh/isolated watchlist toggling (two-user isolation), no-op on invalid
     `cg_id`, inactive-coin soft-hide (excluded from `get_coin_ids_for_user`,
     toggle no-op, search filtering — via `mock.call_args`), and `search`-term
     preservation across pagination. Two `@expectedFailure` bugs: the market index
     prev/next links drop `sort`/`direction` (→ step 7.7), and `add_remove_to_watchlist`
     honors an off-site `next` (open redirect; verified `Location: https://evil.example/`
     → step 4.2). Inactive-coin behavior kept green as a characterization pending
     the steps 11.6/12 visibility decision.
   - 2.5 ✅ Add `portfolio` tests for create, edit, delete, first sell, oversell,
     negative/zero values, high page numbers, FIFO lots, and mocked overview
     market data. Green: FIFO `build_holdings` (single/multi lots, partial/full/
     spanning sells, coin isolation), overview math against a mocked price
     (avg buy price, cost basis, UPL, allocation), create/edit/delete workflows,
     and oversell-on-existing-balance rejection. 12 `@expectedFailure` bugs:
     oversold-ledger `IndexError` (→ 11.1), div-by-zero on zero prices (→ 11.5),
     `get_coin_balance` returning `None` and the resulting first-sell `TypeError`
     (→ 10.2/10.4), negative/zero amount and zero price accepted (→ 10.1),
     non-edit-aware sell edit (→ 10.4), unvalidated buy edit vs later sells
     (→ 10.5), `EmptyPage` on a high page number (→ 7.5), wrong delete message
     wording (→ 10.7), and the delete-path open redirect (→ 4.3). Missing-market
     holdings kept green as a characterization pending step 11.4. (This subtask
     was completed directly rather than by a sub-agent, which was interrupted.)

   Verification:

   - ✅ The suite runs offline: proved by black-holing HTTP (`HTTP(S)_PROXY` to a
     dead port) with `COINGECKO_KEY=dummy` — 120 tests pass, 0 network hits. This
     also surfaced and fixed 3 tests whose `assertRedirects` was silently fetching
     a market-rendering redirect target (now `fetch_redirect_response=False`).
   - ✅ Known current bugs are captured as executable specs: 22 `@expectedFailure`
     tests across `common` (8), `coins` (2), and `portfolio` (12) assert the
     correct behavior and fail today, flipping to XPASS as each later step lands.

   Result: 120 tests, all green, 22 expected failures. No application code was
   changed in this section (tests + `common/test_utils.py` only).

3. **Harden project configuration and security defaults**

   Goal: remove production footguns before deeper refactors add more surface area.

   - 3.1 ✅ Replace wildcard production `ALLOWED_HOSTS` with environment-driven hosts.
     Decision: branch on `DEBUG`. Dev defaults to `["localhost", "127.0.0.1"]`;
     production requires `ALLOWED_HOSTS` via `env_list` and raises
     `ImproperlyConfigured` if `*` is present (wildcard never allowed in prod).
     Django's test runner appends `testserver` automatically, so tests need no
     host env var; CI (DEBUG=True) uses the localhost default. Added the env var
     to `.env.example`/README.
   - 3.2 ✅ Require a real secret key outside development.
     Decision: `if DEBUG:` uses a hardcoded, obviously-insecure fallback
     (`"dev-insecure-do-not-use-in-production"`) chosen over a per-process random
     key for stability/auditability; production (`else`) requires `SECRET_KEY`
     and raises when unset. The fallback is unreachable when `DEBUG` is False.
     `SECRET_KEY` moved below the `DEBUG` line so it can consume it. Removed
     `SECRET_KEY` from CI so CI exercises the zero-config path.
   - 3.3 ✅ Parse `CSRF_TRUSTED_ORIGINS` safely instead of raising raw `KeyError`.
     Decision: already routed through `env_list` (raises `ImproperlyConfigured`,
     not `KeyError`); the remaining fix was the unconditional requirement. Now
     branches on `DEBUG` — dev defaults to
     `["http://localhost:8000", "http://127.0.0.1:8000"]` (scheme + runserver
     port), production still required plus a light guard that rejects entries
     missing a `://` scheme (prevents silent CSRF 403s). Removed from CI;
     completes the zero-config fresh-checkout story (with 3.2).
   - 3.4 ✅ Add production security settings for HTTPS redirect, secure cookies, HSTS,
     and proxy SSL handling where appropriate.
     Decision (deploy target confirmed as **Railway/PaaS**, **conservative HSTS
     ramp**): a single `if not DEBUG:` block — `SECURE_SSL_REDIRECT`
     (env-overridable kill-switch, default True), hardcoded
     `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`, HSTS env knobs
     (`SECURE_HSTS_SECONDS` default 3600, subdomains/preload OFF, ramp toward 1yr
     via env), and `SECURE_PROXY_SSL_HEADER` gated on an opt-in
     `TRUST_PROXY_SSL_HEADER` flag (Railway sets it `true`; default False avoids
     the spoofable-header risk and off-behind-proxy redirect loop). Simulated-prod
     `check --deploy` clears W004/W008/W012/W016; remaining W005/W021 are the
     accepted conservative-HSTS choices. Health-check ↔ SSL-redirect interaction
     and `SECURE_REDIRECT_EXEMPT` mitigation left as a step-16 breadcrumb.
   - 3.5 ✅ Replace `PYTHON_ENV != "production"` with an explicit debug/env parser that
     fails closed.
     Decision: dedicated boolean `DEBUG = env_bool("DJANGO_DEBUG", default=False)`
     (approach A). Fail-closed — unset → production; a malformed value ("prod",
     "Production") raises instead of silently enabling DEBUG. `PYTHON_ENV` removed
     entirely (no alias; nothing else read it). Dev opt-in (`DJANGO_DEBUG=true`)
     added to CI env and `scripts/verify_setup.sh` (`${DJANGO_DEBUG:-true}`) in the
     same change so CI/fresh checkouts stay green; `.env.example` ships it.
     Verified: dev path green (121 tests), unset-in-clean-env raises
     `ImproperlyConfigured` for required vars, and `DJANGO_DEBUG=prod` raises the
     boolean-coercion error. NOTE: existing local `.env` files must add
     `DJANGO_DEBUG=true` or they now boot into production posture.
   - 3.6 ✅ Rename timeout settings with units, for example
     `CACHE_SUPPORTED_COINS_TIMEOUT_SECONDS`.
     Decision: `CACHE_SUPPORTED_COINS_TIMEOUT` → `CACHE_SUPPORTED_COINS_TIMEOUT_SECONDS`
     and `CACHE_INDEX_TABLE_DATA_TIMEOUT` → `CACHE_MARKET_PAGE_TIMEOUT_SECONDS`
     (stem renamed too — the old name was misleading; the timeout applies to
     per-page market data, not just the index). Internal module constants only,
     no env/deploy impact. Local `services.py` aliases left as-is (proportionate).
     The `runapscheduler.py:51` seconds-as-minutes bug was noted but left for
     step 6.4.
   - 3.7 ✅ Split runtime and development dependencies if this will be deployed.
     Decision (deploy target Railway confirmed): two-file split, `requirements.txt`
     (17 runtime lines) + `requirements-dev.txt` (`-r requirements.txt` + ruff,
     pre-commit and their transitives). Kept the full partitioned freeze — every
     pin retained, union reassembles to the original 28 lines exactly. Chosen over
     pyproject `[project]` packaging (b/c) since this is a non-library app and
     requirements.txt is already authoritative; Nixpacks then installs runtime-only
     for prod automatically. CI switched to the dev file; README/AGENTS updated;
     breadcrumb added that the prod build must install `requirements.txt` only.

   Verification:

   - ✅ Simulated-prod `manage.py check --deploy` clears W004/W008/W012/W016; only
     W005/W021 remain, the deliberate conservative-HSTS choices (subdomains/preload
     off), documented and accepted.
   - ✅ Missing production secrets fail closed: with `DJANGO_DEBUG` unset (production
     posture) and secrets stripped, settings import raises `ImproperlyConfigured`
     naming the missing required var (SECRET_KEY / ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS),
     rather than silently running with DEBUG=True.

   Result: section 3 complete. All config footguns removed — no wildcard hosts, no
   shared/implicit secret, safe CSRF parsing, production security block (SSL
   redirect, secure cookies, conservative HSTS, opt-in proxy SSL header), a
   fail-closed `DJANGO_DEBUG` parser (replacing `PYTHON_ENV`), unit-named cache
   timeouts, and a runtime/dev dependency split. Suite stays green (121 tests, 23
   expected failures) throughout; each change verified in both dev and simulated-prod
   postures.

4. **Centralize safe redirect handling**

   Goal: close the open-redirect risk before broad view cleanup.

   - 4.1 ✅ Added `common.utils.get_safe_redirect_url(request, redirect_to)`,
     a URL-returning helper that strips input, validates it against
     `{request.get_host()}` with `require_https=request.is_secure()`, and returns
     `None` for missing, blank, or unsafe targets.
   - 4.2 ✅ Used `get_safe_redirect_url` in
     `coins.views.add_remove_to_watchlist`; valid local `next` targets are still
     honored, while external/protocol-relative targets fall back to
     `coins:index`. Backslash/malformed redirect policy remains deferred to 4.5.
   - 4.3 ✅ Used `get_safe_redirect_url` in
     `portfolio.views.delete_portfolio_transaction`; safe local `next` targets
     are still honored, while unsafe external targets fall back to the existing
     `portfolio:add_transaction` redirect. Query-string preservation remains
     deferred to 4.4.
   - 4.4 ✅ Portfolio all-transactions delete forms now build `next`
     from normalized validated context (`page`, `sort`, `direction`) instead
     of raw request query strings; unrelated query keys are not propagated and
     edit-page deletes still return to the add-transaction page.
   - 4.5 ✅ Added view-level regression coverage for external,
     protocol-relative, and dangerous backslash/scheme-smuggling `next` values;
     no helper policy change, relying on Django's allowed-host validation.

   Verification:

   - Crafted `next=https://external.example` falls back to a safe local route.
   - Existing valid local return paths still work.

5. **Create a CoinGecko client boundary**

   Goal: keep external HTTP behavior out of views, scheduler logic, and portfolio
   calculations.

   - 5.1 ✅ Replace module-level request helpers with a `CoinGeckoClient` or equivalent
     service object.
     Decision: added a `CoinGeckoClient` class in `coins/services.py` holding
     api_key/base_url/timeouts plus an instance-level `threading.local()` session,
     with all HTTP/session/sort/cache logic moved onto it as `list_supported_coins`,
     `get_coin_count`, `get_page_count`, `get_markets`, and private `_session`/`_sort`.
     A module-level singleton `_default_client` backs the existing module functions,
     now thin one-line delegators, and the `SUPPORTED_COINS_TIMEOUT`/`PAGE_DATA_TIMEOUT`
     constants stay — so consumers (`coins/views.py`, `portfolio/services.py`,
     `runapscheduler.py`) and the function-level test seam are untouched. Behavior is
     verbatim (same cache keys/timeouts, no-cache-when-ids, Python-side sort, double
     `res.json()`); timeouts/status/errors (5.2), Decimal (5.3), cache policy (5.4),
     and test injection (5.5) build on this seam later.
   - 5.2 ✅ Add explicit request timeouts, status handling, structured errors, and
     response normalization.
     Decision: added `(3.05, 10.0)` connect/read timeouts as hardcoded module
     constants (`CONNECT_TIMEOUT`/`READ_TIMEOUT`), injectable per-instance via the
     client constructor. New `coins/exceptions.py` holds the hierarchy: base
     `CoinGeckoError` → `CoinGeckoUnavailableError` (→ `CoinGeckoServerError`),
     `CoinGeckoRateLimitError` (carries `retry_after`), `CoinGeckoAuthError`,
     `CoinGeckoResponseError`. A private `_request` routes both `.get()` calls
     through one place mapping transport errors → Unavailable, 429 → RateLimit
     (captures `Retry-After`), 401/403 → Auth, 5xx → Server, `raise_for_status`
     catch-all → Response, malformed JSON → Response — always `raise ... from exc`
     so no `requests.*` escapes. Normalization: single JSON decode (removes the
     double `res.json()` bug) with container-shape validation BEFORE any
     `cache.set` — `list_supported_coins` requires a non-empty `list[dict]` (empty
     or non-list → Response, never cached), `get_markets` requires a `list` (empty
     is legitimate for unknown ids; non-list → Response, protects `_sort`). Added a
     minimal urllib3 `Retry(total=2, backoff_factor=0.5, status_forcelist=[429,500,
     502,503,504], allowed_methods=["GET"], respect_retry_after_header=True)` mounted
     on the session (no new dependency). `coins.W001` kept unchanged as a config-time
     pre-flight nudge. Client RAISES; consumers stay unguarded (catching is 5.6),
     no Decimal/field coercion (5.3). Suite stays green: 131 tests, 21 expected
     failures, no XPASS flips.
   - 5.3 ✅ Convert numeric API values with `Decimal(str(value))` where financial
     calculations need decimals.
     Decision: Option B (consumer-side). Converted only `current_price` — the sole
     market field a financial calculation consumes — at `portfolio/services.py`
     via `Decimal(str(coin["current_price"]))`, replacing `Decimal(coin["current_price"])`
     which fed a binary `float` straight into `Decimal` and captured float noise.
     `str()` first yields the shortest round-trippable decimal the value represents.
     All other numeric market fields (`ath`, `market_cap`, `total_volume`, the two
     `price_change_percentage_*`) are display-only, flow only through the format
     filters, and are left as floats: display-field Decimalization is deferred to
     step 8 (which rewrites formatting around `Decimal`) and key normalization to
     12.4. No `None`/`or 0` fallback added — missing-price semantics belong to
     step 11.4/11.5. Client, cache, and the `common/test_utils.py` float factory
     untouched (the factory's floats survive `Decimal(str(...))` unchanged).
     Suite stays green: 131 tests pass, 21 expected failures, no XPASS flips.
   - 5.4 ✅ Define cache behavior for supported coins, market pages, and id-specific
     market data.
     Decision: made the existing policy explicit and correct without a strategy
     overhaul. Replaced the `has_key`+`get` double-lookup in `list_supported_coins`
     and `get_markets` with a single `cache.get(key, _MISS)` against a distinct
     module-level `_MISS = object()` sentinel (not `None`, so a legitimately cached
     empty market page stays distinguishable from a miss; also closes the TOCTOU
     window where an entry expiring between `has_key` and `get` returned `None`).
     Id-specific market data (search/watchlist/portfolio) stays UNCACHED — the id
     sets are arbitrary, already-paginated user input with unbounded key
     cardinality against an unevicted DB cache table; `get_markets` now branches so
     the "ids given" path is the explicit no-cache branch (empty ids still `[]`),
     with the shared HTTP+list-shape-validation extracted to `_fetch_markets`.
     Both keys carry a `CACHE_VERSION = "v1"` prefix (`v1:supported_coin_list`,
     `v1:coin_list_page_{page}`) so a payload-shape change can invalidate stale
     pre-deploy pickles by bumping it; the market-page key stays page-only
     (documented: CoinGecko is always queried `market_cap_desc`/USD and
     sort/direction apply post-cache, so they are not part of the key). `_sort` is
     now non-mutating (`sorted(...)` instead of in-place `list.sort`, keeping the
     `rank`/`asc` early-return passing the original through) so a cached value is
     never mutated in place — latent-safe for backends that return shared refs;
     harmless-but-correct for `DatabaseCache` which unpickles a fresh copy per get.
     Timeouts unchanged (2h/60s, already unit-named post-3.6) and documented; the
     scheduler interval-unit bug is left to step 6. Added a class docstring in
     `coins/services.py` stating the three-part cache contract and a matching note
     in the AGENTS.md caching section. Public delegator names and the two timeout
     constants (the 5.1 seam) are preserved, so test patch targets are unchanged.
     Suite stays green: 131 tests pass, 21 expected failures, no XPASS flips.
   - 5.5 ✅ Make tests inject fake market responses without patching deep internals.
     Decision: Option C — a constructor `session=` dependency-injection seam for the
     new service tests, with the existing public delegator-patching seam
     (`coins.views.get_coin_list_with_market` etc.) kept unchanged for view/portfolio
     tests. `CoinGeckoClient.__init__` gained a `session=None` param; `_session()`
     returns the override when set, else the existing thread-local branch — default
     `None` keeps production behavior byte-identical, so delegators, timeout
     constants, and public names are untouched. No new dependency: canned responses
     are built with stdlib via two helpers added to `common/test_utils.py` —
     `fake_response(status, payload, body, headers)` returns a REAL
     `requests.models.Response` (faithful `.json()`/`.raise_for_status()`) and
     `fake_session(response, error)` returns a Mock whose `.get` returns the
     response or raises, both reusing `make_market_coin`/`market_response`. New
     `coins/test_services.py::CoinGeckoClientTest` drives the client through PUBLIC
     methods only, covering success (markets + supported list, asserting
     URL/params/timeout), timeout/connection→Unavailable, 429→RateLimit (incl.
     `retry_after`), 401/403→Auth, 500/503→Server, 404→Response, malformed
     JSON→Response, empty/non-list shape→Response, empty ids→`[]` with `.get` not
     called, cache policy (page cached once, supported once, id-specific NOT cached
     → two calls), and `_sort` tolerating a coin missing the sort key. Cache tests
     use a class-level `@override_settings` LocMemCache override + `cache.clear`
     cleanup (the production `DatabaseCache` table is not created by the test
     runner). Existing 131 tests left unmigrated. The urllib3 Retry adapter is
     intentionally NOT unit-covered — injection bypasses it and the Verification
     block does not require retry coverage. Suite: 148 tests pass (+17), 21 expected
     failures unchanged, no unexpected failures, no XPASS flips.
   - 5.6 ✅ Add user-facing graceful fallbacks for CoinGecko downtime or malformed data.
     Decision: per-view `try/except CoinGeckoError` around the market call(s) in
     `render_index` (spanning `get_page_count()` too), `render_search`,
     `render_watchlist`, and `portfolio_overview` — no middleware, no generic-page
     decorator. The shared except-body is factored into `common/utils.py`:
     `handle_market_unavailable(logger, exc)` logs (via `log_coingecko_failure`) and
     returns `{"coin_list": [], "market_unavailable": True}` to merge into the
     context; the scheduler reuses `log_coingecko_failure` directly. Delivery is a
     single `market_unavailable` context flag (NOT Django `messages`), rendering an
     in-place banner with one copy — "Market data is temporarily unavailable. Please
     try again shortly." — at HTTP 200 (owner-chosen; the page shell/navbar/search/
     auth stay usable). Templates updated: `index.html` guards the previously
     unconditional `coins_table.html` include + pagination; `search.html`/
     `watchlist.html` gain an `{% elif market_unavailable %}` branch distinct from
     their genuine-empty states; `overview.html` hides both the summary tiles and the
     P/L table behind the flag (keeping the "See all transactions" link). Portfolio
     shows the banner only and does NOT render holdings-without-prices — that partial
     path is step 11.4. Tiered logging at every catch site: Unavailable/Server/
     RateLimit → `logger.warning(..., exc_info=...)`, Auth/Response → `logger.error`.
     Scheduler `save_new_supported_coins` catches, logs, and returns (skips
     `bulk_create`) so neither the interval job nor `--run-now` crashes the
     `BlockingScheduler`. `coins.W001` kept unchanged (complementary deploy-time
     pre-flight vs. request-time `CoinGeckoAuthError`). AGENTS.md "CoinGecko
     integration & caching" corrected: the false "No timeouts, status checks, or
     retries" line now describes timeouts + bounded urllib3 retry + structured
     `CoinGeckoError` caught by consumers, and `_sort_coin_list` → `_sort` (static
     method on `CoinGeckoClient`). New tests patch the 5.5 delegator seam with
     `side_effect=`: index page-count-fails and market-fails (the latter
     `CoinGeckoResponseError`, covering "malformed data"), search-fails,
     watchlist-fails, portfolio overview-fails (asserts no P/L metrics), and
     scheduler-fails (in a `TransactionTestCase` because `@close_old_connections`
     closes the DB connection; asserts no raise + `Coin` count unchanged) — all
     asserting 200 + banner copy + no 500. Suite: 154 tests pass (+6), 21 expected
     failures unchanged, no unexpected failures, no XPASS flips.

   > Note: Step 1.2 made `COINGECKO_KEY` default to empty instead of raising at
   > settings import. As a provisional measure, a Django system check
   > (`coins.W001` in `coins/apps.py`) warns when the key is unset so the missing
   > config is still visible via `manage.py check`. This check should be revisited
   > here — once the client boundary does explicit status handling (5.2) and
   > raises a clear `ImproperlyConfigured`/structured error on a missing or
   > rejected key, the warning may be redundant and can be removed or folded in.

   Verification:

   - ✅ Service tests cover success, timeout, non-2xx (429/401/403/5xx/404),
     malformed JSON, missing/empty/non-list shape, empty ids, and cache hits
     (`coins/test_services.py`, 17 tests via the injected-`session` seam).
   - ✅ Views do not make real network calls during tests: all market data is
     mocked at the delegator seam documented in `common/test_utils.py`; the whole
     suite runs offline.
   - ✅ CoinGecko downtime/malformed data degrades gracefully instead of 500ing:
     view/scheduler tests patch the seam with `side_effect=CoinGeckoError` and
     assert a 200 in-place banner (and a non-crashing scheduler).

   Result: section 5 complete. All CoinGecko HTTP now lives behind a
   `CoinGeckoClient` boundary (`coins/services.py`) with explicit (connect, read)
   timeouts, a bounded urllib3 retry, status→structured-error mapping
   (`coins/exceptions.py`), single-decode response normalization, versioned/
   sentinel-based caching (id-specific requests deliberately uncached),
   consumer-side `Decimal(str(...))` for the one financially-computed field, a
   constructor `session=` test-injection seam, and user-facing "market data
   temporarily unavailable" fallbacks (HTTP 200, in-place banner) across the
   market/search/watchlist/portfolio views plus a catch-and-log scheduler. The
   `coins.W001` pre-flight key check was reviewed per the note below and
   **kept** — it complements the runtime `CoinGeckoAuthError` (config-time vs.
   request-time signals). Suite: 154 tests, 21 expected failures, green
   throughout; each subtask verified in isolation before the next began.

6. **Refactor coin catalog sync and scheduler responsibilities**

   Goal: separate one-shot data sync from the long-running scheduler and fix stale
   catalog behavior.

   - 6.1 Move catalog sync into a reusable domain function.
   - 6.2 Add a one-shot management command for syncing supported coins.
   - 6.3 Keep the APScheduler command thin and focused on scheduling.
   - 6.4 Fix the interval unit bug by using seconds or an explicitly named minutes
     value.
   - 6.5 Change sync from create-only to update/upsert existing names and symbols.
   - 6.6 Decide how to mark coins inactive when they disappear from CoinGecko.
   - 6.7 Log counts for created, updated, deactivated, skipped, and failed rows.

   Verification:

   - Scheduler interval matches the documented cadence.
   - Sync tests cover create, update, unchanged, missing/deactivated, and API
     failure paths.

7. **Replace ad hoc query, sort, pagination, and URL building**

   Goal: make list/table behavior consistent across `coins`, `portfolio`, and
   future screens.

   - 7.1 Replace the split `validate_common_params` plus `get_common_params` contract
     with one normalized query-state helper.
   - 7.2 Strip and validate page, sort, and direction in one place.
   - 7.3 Build encoded query strings through `QueryDict` or `urlencode`.
   - 7.4 Preserve intended params consistently across sort links and pagination.
   - 7.5 Fix portfolio transaction page clamping by using real `Paginator.num_pages`.
   - 7.6 Make the common pagination partial generic; remove the hard-coded "Back to
     Market" action from it.
   - 7.7 Make the market index use the same pagination behavior as other pages.

   Verification:

   - High page values do not raise `EmptyPage`.
   - Search terms containing spaces, ampersands, equals signs, or question marks
     produce valid links.
   - Sorting and pagination preserve the same state on every list view.

8. **Fix shared financial formatting**

   Goal: stop displaying incorrect values before portfolio metric work expands.

   - 8.1 Rewrite number formatting around `Decimal` and explicit sign handling.
   - 8.2 Cover negative non-integers, tiny positive and negative values, zero, `None`,
     invalid strings, and large values.
   - 8.3 Normalize `-0.00%` to `0%` where appropriate.
   - 8.4 Decide whether zero percentage change should be neutral rather than danger.
   - 8.5 Remove unused template filters if they have no planned use.

   Verification:

   - Formatting tests document every supported display case.
   - Portfolio loss values render correctly.

9. **Settle user ownership and auth model strategy**

   Goal: avoid painful migrations after more account and ownership features are
   added.

   - 9.1 Decide whether this app will ever need a custom user model. If yes, plan
     that migration explicitly before adding profile data.
   - 9.2 In the near term, replace direct `django.contrib.auth.models.User` model
     references with `settings.AUTH_USER_MODEL`.
   - 9.3 Use `get_user_model()` in tests and runtime code that needs the concrete
     class.
   - 9.4 Document deletion behavior for users, watchlist rows, and portfolio history.
   - 9.5 Decide whether account URLs should stay global or gain an `accounts`
     namespace with compatibility aliases.

   Verification:

   - Migrations are explicit and reviewed.
   - User-owned data isolation tests pass for watchlist and portfolio flows.

10. **Move portfolio ledger rules into a domain service**

    Goal: make transaction correctness independent of view code.

    - 10.1 Add positive amount and positive price validation at the form/model layer.
    - 10.2 Make `get_coin_balance()` return `Decimal("0")` for no rows.
    - 10.3 Centralize create, edit, and delete validation in a portfolio service.
    - 10.4 Make sell validation edit-aware.
    - 10.5 Validate buy edits and buy deletes against later sells, not just final
      balance.
    - 10.6 Wrap balance-changing writes in a database transaction and consider
      row-level locking for concurrent sells.
    - 10.7 Fix the delete error message for the guarded buy-delete case.
    - 10.8 Add deterministic ordering for ledger calculations, such as `created, id`.

    Verification:

    - Tests cover first sell, oversell, valid sell edit, invalid buy edit,
      invalid buy delete, concurrent-risk boundaries where feasible, and normal
      create/edit/delete success.

11. **Harden portfolio holdings and metrics**

    Goal: make the overview resilient to bad ledgers, missing prices, and naming
    ambiguity.

    - 11.1 Make `build_holdings()` fail gracefully or return a domain error on
      oversold history instead of raising `IndexError`.
    - 11.2 Rename row `value` to `cost_basis`.
    - 11.3 Add explicit `market_value` per holding.
    - 11.4 Handle missing market data without dropping holdings silently.
    - 11.5 Avoid division by zero when current prices are zero or unavailable.
    - 11.6 Decide whether inactive/delisted coins should remain visible in historical
      transactions and overview.
    - 11.7 Consider a user-entered trade timestamp separate from `created`.
    - 11.8 Add indexes for common queries such as `(user, coin, created)` and
      `(user, created)`.

    Verification:

    - FIFO tests cover partial sells, full sells, multiple lots, same timestamp
      ordering, missing prices, zero market value, and inactive coins.

12. **Clarify market sorting semantics**

    Goal: make table sorting match user expectations or label the limitation
    clearly.

    - 12.1 Decide whether sorting should be global or current-page only.
    - 12.2 Use CoinGecko-supported API ordering where possible for market-wide sorts.
    - 12.3 For search and watchlist, either fetch and sort the whole relevant id set
      before pagination when feasible, or keep current-page sorting explicit.
    - 12.4 Normalize market payload keys before templates so CoinGecko `id` is exposed
      as `cg_id`.
    - 12.5 Add deterministic watchlist ordering with timestamps.

    Verification:

    - Sorting tests document index, search, and watchlist behavior.
    - Pagination and sorting compose predictably.

13. **Improve admin and operational visibility**

    Goal: make support and data repair possible without violating domain rules.

    - 13.1 Register `Watchlist` in admin with useful filters and search.
    - 13.2 Decide whether `CoinAdmin` is read-only except `is_active` or supports
      manual repair with `cg_id` visible.
    - 13.3 Fix `PortfolioTransactionAdmin` timestamp handling with `readonly_fields`.
    - 13.4 Decide whether portfolio transactions are immutable audit records.
    - 13.5 Add admin smoke tests for important add, view, and list pages.
    - 13.6 Add logging around market API failures, catalog sync, and portfolio domain
      validation failures.

    Verification:

    - Admin pages load without form field errors.
    - Admin actions align with the chosen data ownership policy.

14. **Polish account flows**

    Goal: make authentication feel intentional instead of merely wired up.

    - 14.1 Add registration success messages.
    - 14.2 Preserve an intended destination through registration when appropriate.
    - 14.3 Decide whether users should be automatically logged in after registering.
    - 14.4 Add password reset/change routes if this is meant to be usable outside a
      demo environment.
    - 14.5 Improve login/register templates while keeping them consistent with the
      server-rendered Bootstrap app.

    Verification:

    - Account tests cover anonymous and authenticated navbar states, success
      messages, redirects, and template rendering.

15. **Polish table-heavy UI and empty/error states**

    Goal: improve the app experience after behavior is stable.

    - 15.1 Wrap market, watchlist, overview, and transaction tables in responsive
      containers.
    - 15.2 Replace ambiguous text actions with clear commands such as "Manage",
      "Add transaction", "Edit", and "Delete".
    - 15.3 Add delete confirmation for portfolio transactions.
    - 15.4 Improve empty states for empty catalog, empty search, empty watchlist,
      empty portfolio, and no transactions for a specific coin.
    - 15.5 Show graceful messages when market data is unavailable.
    - 15.6 Preserve page/sort/search context after actions where useful.
    - 15.7 Keep the styling restrained and workflow-focused; this is a data app, not
      a marketing site.

    Verification:

    - Manual browser pass across anonymous and authenticated flows.
    - Mobile-width pass for wide tables and form layouts.

16. **Prepare deployment and runtime operations**

    Goal: make production assumptions explicit after application behavior is
    reliable.

    - 16.1 Document process topology: web process, scheduler process, database, cache,
      static files, and secrets.
    - 16.2 Add a production server dependency or deployment-specific requirements.
    - 16.3 Decide whether database cache is acceptable or whether Redis/memcached is
      needed.
    - 16.4 Add a health check route.
    - 16.5 Add basic production logging and error reporting hooks.
    - 16.6 Align `.env` behavior across local management commands and ASGI/WSGI, or
      document that process managers provide production env vars.

    Verification:

    - Fresh setup documentation works from a clean checkout.
    - Production checks, migrations, static collection, cache setup, and scheduler
      startup are documented as separate steps.

## Suggested First Pull Requests

1. Environment/settings import cleanup plus `.env.example`.
2. Offline test baseline with CoinGecko mocked.
3. Safe redirect helper and tests.
4. CoinGecko client boundary with timeout/error handling.
5. Common query-state and pagination refactor.
6. Portfolio ledger service and validation fixes.
7. Portfolio metrics/holdings hardening.
8. UI/admin/account polish.
