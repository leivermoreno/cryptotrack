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
   - 1.7 Add a short setup verification path such as `manage.py check`, migrations,
     cache table creation, and tests.

   Verification:

   - `venv/bin/python manage.py check`
   - `CRYPTO_COINGECKO_KEY=dummy venv/bin/python manage.py test`

2. **Establish a safety-net test baseline**

   Goal: capture current intended behavior before changing shared helpers or
   business rules.

   - 2.1 Mock CoinGecko in all view tests that currently touch market data.
   - 2.2 Add direct tests for `accounts` login, logout, registration, and redirects.
   - 2.3 Add direct tests for `common` query validation, pagination, formatting, and
     sort-link generation.
   - 2.4 Add `coins` tests for watchlist toggling, invalid CoinGecko ids, inactive
     coins, query preservation, and unsafe `next` values.
   - 2.5 Add `portfolio` tests for create, edit, delete, first sell, oversell,
     negative/zero values, high page numbers, FIFO lots, and mocked overview
     market data.

   Verification:

   - The suite can run offline with a dummy CoinGecko key.
   - Tests fail for at least the known current bugs before fixes are applied.

3. **Harden project configuration and security defaults**

   Goal: remove production footguns before deeper refactors add more surface area.

   - 3.1 Replace wildcard production `ALLOWED_HOSTS` with environment-driven hosts.
   - 3.2 Require a real secret key outside development.
   - 3.3 Parse `CSRF_TRUSTED_ORIGINS` safely instead of raising raw `KeyError`.
   - 3.4 Add production security settings for HTTPS redirect, secure cookies, HSTS,
     and proxy SSL handling where appropriate.
   - 3.5 Replace `PYTHON_ENV != "production"` with an explicit debug/env parser that
     fails closed.
   - 3.6 Rename timeout settings with units, for example
     `CACHE_SUPPORTED_COINS_TIMEOUT_SECONDS`.
   - 3.7 Split runtime and development dependencies if this will be deployed.

   Verification:

   - `manage.py check --deploy` has only accepted, documented warnings.
   - Missing production secrets fail with clear configuration errors.

4. **Centralize safe redirect handling**

   Goal: close the open-redirect risk before broad view cleanup.

   - 4.1 Add a small helper around Django's allowed-host redirect validation.
   - 4.2 Use it for watchlist toggles in `coins.views.add_remove_to_watchlist`.
   - 4.3 Use it for portfolio delete redirects.
   - 4.4 Preserve useful query strings only after validation.
   - 4.5 Add regression tests for external URLs and malformed `next` values.

   Verification:

   - Crafted `next=https://external.example` falls back to a safe local route.
   - Existing valid local return paths still work.

5. **Create a CoinGecko client boundary**

   Goal: keep external HTTP behavior out of views, scheduler logic, and portfolio
   calculations.

   - 5.1 Replace module-level request helpers with a `CoinGeckoClient` or equivalent
     service object.
   - 5.2 Add explicit request timeouts, status handling, structured errors, and
     response normalization.
   - 5.3 Convert numeric API values with `Decimal(str(value))` where financial
     calculations need decimals.
   - 5.4 Define cache behavior for supported coins, market pages, and id-specific
     market data.
   - 5.5 Make tests inject fake market responses without patching deep internals.
   - 5.6 Add user-facing graceful fallbacks for CoinGecko downtime or malformed data.

   > Note: Step 1.2 made `COINGECKO_KEY` default to empty instead of raising at
   > settings import. As a provisional measure, a Django system check
   > (`coins.W001` in `coins/apps.py`) warns when the key is unset so the missing
   > config is still visible via `manage.py check`. This check should be revisited
   > here — once the client boundary does explicit status handling (5.2) and
   > raises a clear `ImproperlyConfigured`/structured error on a missing or
   > rejected key, the warning may be redundant and can be removed or folded in.

   Verification:

   - Service tests cover success, timeout, non-2xx, malformed JSON, missing
     fields, empty ids, and cache hits.
   - Views do not make real network calls during tests.

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
