# CryptoTrack Refactor Steps (Part 2: Sections 11–16)

Keep completed item explanations to at most two short lines; summarize outcomes
only and avoid implementation detail.

Continuation of `inspection/refactor_steps.md` (part 1), which covers the plan
overview and the completed sections 1–10. This file holds the remaining open
sections 11–16 and is self-contained: **you do not need to read part 1 unless a
task specifically requires it** — skip it by default to keep context small and
avoid contamination from the already-done work.

For reference only, the numbering convention carried over from part 1: subtasks
are numbered `N.M` (e.g. `11.1`) and completed items are marked ✅.

## Ordered Refactor Plan (continued)

11. **Harden portfolio holdings and metrics**

    Goal: make the overview resilient to bad ledgers, missing prices, and naming
    ambiguity.

    - 11.1 ✅ Make `build_holdings()` fail gracefully or return a domain error on
      oversold history instead of raising `IndexError`.
    - 11.2 ✅ Rename row `value` to `cost_basis`.
    - 11.3 ✅ Add explicit `market_value` per holding.
    - 11.4 ✅ Handle missing market data without dropping holdings silently.
    - 11.5 ✅ Avoid division by zero when current prices are zero or unavailable.
    - 11.6 ✅ Decide whether inactive/delisted coins should remain visible in historical
      transactions and overview. Delisted coins stay visible as unpriced, read-only
      holdings; users may close or reduce them but cannot acquire more.
    - 11.7 ✅ Consider a user-entered trade timestamp separate from `created`.
      Added display-only `trade_date` for forms/lists while keeping FIFO and ledger
      ordering based on `created`.
    - 11.8 ✅ Add indexes for common queries such as `(user, coin, created)` and
      `(user, created)`. Added the two useful composites: `(user, coin, created)`
      for ledger paths and `(user, trade_date)` for the default transaction list.

    Verification:

    - FIFO tests cover partial sells, full sells, multiple lots, same timestamp
      ordering, missing prices, zero market value, and inactive coins.

12. **Clarify market sorting semantics**

    Goal: make table sorting match user expectations or label the limitation
    clearly.

    - 12.1 ✅ Decide whether sorting should be global or current-page only.
      Sorting stays current-page only across index, search, and watchlist views.
    - 12.2 ✅ Use CoinGecko-supported API ordering where possible for market-wide sorts.
      Declined; the app keeps one market-cap-desc API query and performs page-local
      sorting after cache reads.
    - 12.3 ✅ For search and watchlist, either fetch and sort the whole relevant id set
      before pagination when feasible, or keep current-page sorting explicit.
      Search and watchlist keep page-local sorting; watchlist page stability is handled
      by deterministic base ordering.
    - 12.4 ✅ Normalize market payload keys before templates so CoinGecko `id` is exposed
      as `cg_id`. Added `cg_id` while retaining `id`, so templates can use the external
      coin id without breaking existing market-data consumers.
    - 12.5 ✅ Add deterministic watchlist ordering with timestamps.
      Added `created` to watchlist rows and ordered ids by `(created, id)` for stable
      pagination.

    Verification:

    - Sorting tests document index, search, and watchlist behavior.
    - Pagination and sorting compose predictably.

13. **Improve admin and operational visibility**

    Goal: make support and data repair possible without violating domain rules.

    - 13.1 ✅ Register `Watchlist` in admin with useful filters and search.
      Added watchlist admin list/search/filter support, FK autocompletes, and a
      read-only created timestamp.
    - 13.2 ✅ Decide whether `CoinAdmin` is read-only except `is_active` or supports
      manual repair with `cg_id` visible. Coin admin is a read-only CoinGecko mirror
      except for `is_active`; `cg_id` is visible but protected.
    - 13.3 ✅ Fix `PortfolioTransactionAdmin` timestamp handling with `readonly_fields`.
      Made `created` read-only in admin and surfaced editable `trade_date` in lists,
      filters, and the detail form.
    - 13.4 ✅ Decide whether portfolio transactions are immutable audit records.
      Portfolio transactions are view-only in admin; user-facing app flows still
      support ledger-validated create, edit, and delete.
    - 13.5 ✅ Add admin smoke tests for important add, view, and list pages.
      Added smoke coverage for coin, watchlist, and read-only portfolio transaction
      admin pages and permissions.
    - 13.6 ✅ Add logging around market API failures, catalog sync, and portfolio domain
      validation failures. Added standard-library logging for market failures, skipped
      sync rows, and rejected portfolio ledger operations.

    Verification:

    - Admin pages load without form field errors.
    - Admin actions align with the chosen data ownership policy.

14. **Polish account flows**

    Goal: make authentication feel intentional instead of merely wired up.

    - 14.1 ✅ Add registration success messages. Decision/solution: keep the
      current redirect-to-login behavior and enqueue a Django success message after
      user creation.
    - 14.2 ✅ Preserve an intended destination through registration when appropriate.
      Decision/solution: safe `next` values are carried through register links/forms
      and the redirect back to login; unsafe targets are dropped.
    - 14.3 ✅ Decide whether users should be automatically logged in after
      registering. Decision/solution: do not auto-login. Registration already
      preserves safe `next` destinations and shows a success message before
      sending the user to login; there is no email verification or profile setup
      flow that would justify changing the auth state here.
    - 14.4 ✅ Add password reset/change routes if this is meant to be usable
      outside a demo environment. Decision/solution: wire Django's built-in
      password reset/change views under the `accounts` namespace, keep the
      existing global auth URL aliases, add minimal Bootstrap/crispy templates,
      and expose forgot-password/change-password links.
    - 14.5 ✅ Improve login/register templates while keeping them consistent with the
      server-rendered Bootstrap app. Decision/solution: keep the existing auth flow
      and polish only the rendered Bootstrap form panels, preserving safe `next`,
      password reset, and cross-links.

    Verification:

    - Account tests cover anonymous and authenticated navbar states, success
      messages, redirects, template rendering, password change, and password reset
      email/token flow.

15. **Polish table-heavy UI and empty/error states**

    Goal: improve the app experience after behavior is stable.

    - 15.1 ✅ Wrap market, watchlist, overview, and transaction tables in responsive
      containers. Wrapped the shared market/watchlist table, portfolio overview table,
      and shared transaction table in Bootstrap responsive containers.
    - 15.2 ✅ Replace ambiguous text actions with clear commands such as "Manage",
      "Add transaction", "Edit", and "Delete". Updated watchlist, market, portfolio
      holding, and transaction form actions to use explicit command labels.
    - 15.3 ✅ Add delete confirmation for portfolio transactions.
      Added a server-rendered confirmation step while preserving POST-only mutation,
      CSRF protection, ledger validation, and safe next redirects.
    - 15.4 ✅ Improve empty states for empty catalog, empty search, empty watchlist,
      empty portfolio, and no transactions for a specific coin. Added scoped Bootstrap
      alerts and restrained actions while keeping unavailable-market states separate.
    - 15.5 ✅ Show graceful messages when market data is unavailable.
      Added a shared unavailable-market partial across market, search, watchlist,
      and portfolio overview pages, separate from true empty states.
    - 15.6 ✅ Preserve page/sort/search context after actions where useful.
      Threaded safe next targets through market add-transaction links and portfolio
      transaction create/edit/delete flows without weakening redirect validation.
    - 15.7 ✅ Keep the styling restrained and workflow-focused; this is a data app,
      not a marketing site. Kept the UI Bootstrap-native and tightened portfolio
      summary hierarchy, secondary navigation weight, and transaction form density.

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
