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
