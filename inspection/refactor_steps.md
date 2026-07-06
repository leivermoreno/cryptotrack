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
marked ✅. Done sections (1–5) are summarized to problem/solution points; open
sections keep their full task lists.

## Ordered Refactor Plan

1. **Make local development and tests reproducible** ✅

   Goal: make every later change verifiable without hidden environment or network
   dependencies.

   - 1.1 ✅ Added `.env.example` with required/optional vars.
   - 1.2 ✅ Stopped requiring the CoinGecko key at settings import (now defaults to `""`).
   - 1.3 ✅ Added an env helper (`env`/`env_bool`/`env_list`) so required vars raise a
     clear `ImproperlyConfigured` (not raw `KeyError`), optional vars have defaults, and
     strip/coerce live in one place. Non-env constants (e.g. `LOGIN_URL`) stay hardcoded;
     actual policies tightened in section 3.
   - 1.4 ✅ Added explicit `LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`.
   - 1.5 ✅ Decision: **PostgreSQL only** for dev/test/prod (no SQLite fallback or test
     settings), to avoid engine divergence in `Decimal` logic. Documented in `README.md`.
   - 1.6 ✅ Added `STATIC_ROOT`, `STORAGES` (`CompressedManifestStaticFilesStorage`), and
     WhiteNoise middleware (after `SecurityMiddleware`) to serve static assets from the
     app process (no CDN).
   - 1.7 ✅ Added `scripts/verify_setup.sh` (check → migrate → createcachetable → test;
     idempotent, stops at first failure).

   Verification: `scripts/verify_setup.sh` runs `check` + the full suite offline (no
   CoinGecko key needed after 1.2).

2. **Establish a safety-net test baseline** ✅

   Goal: capture current intended behavior before changing shared helpers or
   business rules.

   Conventions: known bugs get `@expectedFailure` tests asserting the *correct*
   behavior (they flip to XPASS when fixed); section 2 changes tests only; CoinGecko is
   mocked at the service-function seam (`get_coin_list_with_market`/`get_page_count`,
   patched where imported) via `common/test_utils.py`, so the suite runs offline;
   undecided design questions are characterized green, not marked expected-failure.

   - 2.1 ✅ Mocked CoinGecko in all market-touching view tests; added
     `common/test_utils.py` payload factory.
   - 2.2 ✅ 12 tests for accounts login/logout/register/redirects (asserts against
     `settings.*_REDIRECT_URL`, uses `get_user_model()`). No current bug found.
   - 2.3 ✅ 52 `common` tests, 8 `@expectedFailure`: negative-non-integer truncation in
     `format_number`/`format_amount` (→8.1), `format_number("")` raising (→8.2),
     `-0.00%` (→8.3), `sort_link` not URL-encoding `search` (→7.3/7.4).
   - 2.4 ✅ `coins` watchlist tests (two-user isolation, invalid `cg_id` no-op,
     inactive-coin soft-hide, `search` preservation). 2 `@expectedFailure`: index
     prev/next drop `sort`/`direction` (→7.7), watchlist open redirect (→4.2).
   - 2.5 ✅ `portfolio` tests (FIFO `build_holdings`, overview math, create/edit/delete,
     oversell rejection). 12 `@expectedFailure`: oversold `IndexError` (→11.1),
     div-by-zero on zero prices (→11.5), `get_coin_balance` `None` + first-sell
     `TypeError` (→10.2/10.4), negative/zero amount+price accepted (→10.1),
     non-edit-aware sell edit (→10.4), buy-edit vs later sells (→10.5), high-page
     `EmptyPage` (→7.5), wrong delete message (→10.7), delete open redirect (→4.3).

   Verification: suite runs offline (proven by black-holing HTTP); 22 `@expectedFailure`
   tests capture known bugs as executable specs.

   Result: 120 tests green, 22 expected failures; no app code changed (tests +
   `common/test_utils.py` only).

3. **Harden project configuration and security defaults** ✅

   Goal: remove production footguns before deeper refactors add surface area.

   - 3.1 ✅ `ALLOWED_HOSTS` branches on `DEBUG`: dev `["localhost","127.0.0.1"]`; prod
     requires `env_list` and raises if `*` is present. Test runner adds `testserver`.
   - 3.2 ✅ `SECRET_KEY`: dev uses an obviously-insecure fallback; prod requires it and
     raises when unset (fallback unreachable when `DEBUG` off). Removed from CI.
   - 3.3 ✅ `CSRF_TRUSTED_ORIGINS` via `env_list`: dev defaults to localhost:8000; prod
     required, with a guard rejecting entries missing a `://` scheme (prevents silent
     CSRF 403s).
   - 3.4 ✅ Production `if not DEBUG:` block (Railway/PaaS, conservative HSTS ramp):
     `SECURE_SSL_REDIRECT` (env kill-switch, default True), hardcoded secure session/CSRF
     cookies, HSTS env knobs (`SECURE_HSTS_SECONDS` default 3600, subdomains/preload off),
     and `SECURE_PROXY_SSL_HEADER` gated on opt-in `TRUST_PROXY_SSL_HEADER`. Clears
     W004/W008/W012/W016.
   - 3.5 ✅ `DEBUG = env_bool("DJANGO_DEBUG", default=False)`, fail-closed (unset →
     production; malformed value raises). Removed `PYTHON_ENV` entirely; added
     `DJANGO_DEBUG=true` to CI and `scripts/verify_setup.sh`.
   - 3.6 ✅ Renamed cache timeouts with units: `CACHE_SUPPORTED_COINS_TIMEOUT_SECONDS`
     and `CACHE_MARKET_PAGE_TIMEOUT_SECONDS` (stem renamed — applies to per-page market
     data, not just the index). Internal constants only.
   - 3.7 ✅ Split deps: `requirements.txt` (runtime) + `requirements-dev.txt` (`-r` +
     ruff/pre-commit). CI uses the dev file; prod build installs runtime only.

   Verification: simulated-prod `check --deploy` clears W004/W008/W012/W016 (W005/W021
   remain by the conservative-HSTS choice); missing prod secrets fail closed with a
   named `ImproperlyConfigured`.

   Result: all config footguns removed; suite green (121 tests, 23 expected failures)
   throughout, verified in dev and simulated-prod postures.

4. **Centralize safe redirect handling** ✅

   Goal: close the open-redirect risk before broad view cleanup.

   - 4.1 ✅ Added `common.utils.get_safe_redirect_url(request, redirect_to)`: strips
     input, validates against the request host with `require_https=request.is_secure()`,
     returns `None` for missing/blank/unsafe targets.
   - 4.2 ✅ Used it in `coins.views.add_remove_to_watchlist` (unsafe `next` falls back to
     `coins:index`).
   - 4.3 ✅ Used it in `portfolio.views.delete_portfolio_transaction` (unsafe `next`
     falls back to `portfolio:add_transaction`).
   - 4.4 ✅ Portfolio all-transactions delete forms build `next` from normalized
     validated context (`page`/`sort`/`direction`), not raw request query strings.
   - 4.5 ✅ Added view-level regression coverage for external, protocol-relative, and
     backslash/scheme-smuggling `next` values.

   Verification: crafted external `next` falls back to a safe local route; valid local
   return paths still work.

5. **Create a CoinGecko client boundary** ✅

   Goal: keep external HTTP behavior out of views, scheduler, and portfolio math.

   - 5.1 ✅ Added `CoinGeckoClient` in `coins/services.py` (api_key/base_url/timeouts +
     thread-local session; all HTTP/session/sort/cache moved onto it as methods). A
     module-level singleton backs the existing functions as thin delegators, so consumers
     and the function-level test seam are unchanged; behavior verbatim.
   - 5.2 ✅ Added `(3.05, 10.0)` connect/read timeouts (injectable) and a structured error
     hierarchy in `coins/exceptions.py` (`CoinGeckoError` → Unavailable/Server, RateLimit
     w/ `retry_after`, Auth, Response). A private `_request` maps every transport/status/
     decode failure and never leaks `requests.*`. Single JSON decode (fixes the double
     `json()` bug) with container-shape validation before any `cache.set`. Added a bounded
     urllib3 `Retry` on idempotent GETs. Client raises; consumers stay unguarded (5.6).
   - 5.3 ✅ Consumer-side `Decimal(str(coin["current_price"]))` in `portfolio/services.py`
     (was `Decimal(float)`, capturing float noise). Display-only fields stay floats
     (Decimalized later in step 8).
   - 5.4 ✅ Made cache policy explicit: single `cache.get(key, _MISS)` sentinel lookup
     (replaces `has_key`+`get`, closes the TOCTOU window); id-specific data stays
     UNCACHED (unbounded key cardinality); `CACHE_VERSION="v1"` key prefixes; market-page
     key is page-only (sort/direction applied post-cache); `_sort` made non-mutating.
     Documented the three-part contract in the class docstring and AGENTS.md.
   - 5.5 ✅ Added a constructor `session=` injection seam for the new service tests
     (default `None` keeps prod byte-identical). Added stdlib `fake_response`/
     `fake_session` helpers to `common/test_utils.py`; `coins/test_services.py` drives
     the client via public methods (success, timeouts, 429/401/403/5xx/404, malformed
     JSON, bad shape, empty ids, cache policy). +17 tests.
   - 5.6 ✅ Per-view `try/except CoinGeckoError` in `render_index`/`render_search`/
     `render_watchlist`/`portfolio_overview`; shared body in
     `common.utils.handle_market_unavailable` (logs + returns
     `{"coin_list": [], "market_unavailable": True}`). Templates render an in-place
     "market data temporarily unavailable" banner at HTTP 200. Scheduler catches, logs,
     and skips instead of crashing. Tiered logging (Unavailable/Server/RateLimit →
     warning; Auth/Response → error). +6 tests.

   Note: `coins.W001` (config-time missing-key warning) was reviewed here and **kept** —
   it complements the request-time `CoinGeckoAuthError` (config-time vs. request-time).

   Verification: service tests cover success/timeout/non-2xx/malformed/shape/empty-ids/
   cache; views make no real network calls (mocked at the delegator seam); downtime
   degrades to a 200 banner and a non-crashing scheduler.

   Result: all CoinGecko HTTP lives behind `CoinGeckoClient` with timeouts, bounded
   retry, structured errors, single-decode normalization, versioned/sentinel caching
   (id-specific uncached), `Decimal(str(...))` for the one financial field, a `session=`
   test seam, and graceful 200 fallbacks. Suite: 154 tests, 21 expected failures.

6. **Refactor coin catalog sync and scheduler responsibilities** ✅

   Goal: separate one-shot data sync from the long-running scheduler and fix stale
   catalog behavior.

   - 6.1–6.3 ✅ Separated sync from scheduling. Problem: catalog sync was entangled
     with the blocking scheduler and had no standalone entry point. Solution: extracted
     `coins.sync.sync_supported_coins()` (fetch + persist); added a one-shot
     `sync_supported_coins` management command as the seeding path; removed
     `runapscheduler --run-now` so `runapscheduler` only registers recurring jobs. Both
     the command and the scheduled job log `CoinGeckoError` via the shared helper and
     skip without crashing.
   - 6.4 ✅ Interval unit bug. Problem: cadence risked a minutes/seconds mismatch.
     Solution: `SUPPORTED_COINS_SYNC_INTERVAL_SECONDS = SUPPORTED_COINS_TIMEOUT + 5*60`,
     passed as `seconds=` (every 2h05m).
   - 6.5–6.6 ✅ Stale catalog. Problem: sync was create-only, so renamed/delisted coins
     never updated. Solution: upsert by `cg_id` (bulk-create missing, bulk-update only
     changed `name`/`symbol`); treat the fetched active list as source of truth —
     returned coins are created/reactivated, active local coins absent from the fetch are
     soft-deactivated (`is_active=False`).
   - 6.7 ✅ Observability. Solution: sync returns structured created/updated/deactivated/
     skipped/failed counts; malformed rows (missing/blank `id`/`name`/`symbol`) are
     counted failed and skipped without aborting; command and job log the counts.

   Verification: interval matches documented cadence; sync tests cover create, update,
   unchanged, missing/deactivated, malformed rows, count logging, and API failures.

7. **Replace ad hoc query, sort, pagination, and URL building** ✅

   Goal: make list/table behavior consistent across `coins`, `portfolio`, and
   future screens.

   - 7.1–7.2 ✅ Split validation contract. Problem: `validate_common_params` (decorator)
     and `get_common_params` (reader) parsed/clamped independently and could diverge.
     Solution: single `common.utils.normalize_query_state()` → `QueryState`
     (`page`/`sort`/`direction`) with `InvalidQueryState` for bad input; decorator and
     reader are now thin wrappers over it, and the decorator syncs only supplied common
     keys back onto `request.GET` (stripped values; blanks removed so defaults apply).
   - 7.3–7.4 ✅ Unsafe URL building. Problem: query strings were concatenated manually,
     breaking on spaces/`&`/`=`/`?` and dropping intended params. Solution:
     `build_query_string()` (backed by `QueryDict.urlencode()`) centralizes
     `page`/`sort`/`direction`/optional `search`; `sort_link`, the shared pagination
     partial, and coins/portfolio form `next` values all use it, so state round-trips.
   - 7.5 ✅ Page clamping. Problem: portfolio clamped against an item count and could
     still raise `EmptyPage`. Solution: `show_all_transactions` and
     `create_portfolio_transaction` clamp via a real Django `Paginator.num_pages`.
   - 7.6 ✅ Generic pagination. Problem: the shared partial hard-coded a "Back to Market"
     action. Solution: renders an optional back action only when callers pass both
     `pagination_back_url` and `pagination_back_label`.
   - 7.7 ✅ Index consistency. Problem: the market index paginated differently from other
     views. Solution: it builds a `Paginator` from the CoinGecko-reported page count and
     uses the same shared partial + `page_obj`; the API still gets the normalized
     requested page.

   Verification: high pages don't raise `EmptyPage`; search terms with spaces/`&`/`=`/`?`
   produce valid links; sort and pagination preserve state on every list view.

8. **Fix shared financial formatting**

   Goal: stop displaying incorrect values before portfolio metric work expands.

   - 8.1 ✅ Rewrite number formatting around `Decimal` and explicit sign handling.
     Decision/solution: `format_number` now coerces with `Decimal(str(value))`,
     formats absolute magnitude, then prepends an explicit sign; small-number
     truncation behavior and `$-12.34` currency display were preserved.
   - 8.2 ✅ Cover negative non-integers, tiny positive and negative values, zero, `None`,
     invalid strings, and large values.
     Decision/solution: added formatter coverage for numeric edge cases and a shared
     private Decimal coercion helper. `format_number`, `format_amount`, and
     `format_percentage` now render `-` for `None`, blank/invalid strings, conversion
     errors, and non-finite values.
   - 8.3 ✅ Normalize `-0.00%` to `0%` where appropriate.
     Decision/solution: `format_percentage` still formats to two decimals first, then
     collapses both formatted zero strings (`0.00` and `-0.00`) to `0%`; real negative
     percentages such as `-0.01%` keep their sign.
   - 8.4 ✅ Decide whether zero percentage change should be neutral rather than danger.
     Decision/solution: zero percentage changes are neutral and return no Bootstrap
     class. `percentage_change_class` now shares `_to_decimal` invalid-input handling
     and classifies using the two-decimal rounded value, so values displayed as `0%`
     are neutral while real negatives such as `-0.01%` remain `text-danger`.
   - 8.5 ✅ Remove unused template filters if they have no planned use.
     Decision/solution: removed the unused registered `multiply` filter; remaining
     registered filters/tags are used by templates or covered by tests.

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
