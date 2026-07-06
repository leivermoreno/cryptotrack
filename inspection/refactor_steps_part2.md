# CryptoTrack Refactor Steps (Part 2: Sections 11–16)

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
      transactions and overview. **Decision (product owner): Option C.** Delisted
      coins (`Coin.is_active=False`) stay visible read-only: their holdings appear in
      the overview as unpriced rows (reusing 11.4 — market fields blank, excluded from
      totals, counted in `unpriced_count`) with a "Delisted" badge, and their
      transactions remain in the all-transactions and per-coin lists. The user may
      *close/adjust* a dead position — sells, deletes, and price-only/amount-reducing
      edits of existing buys are allowed — but may not *acquire more*: creating a new
      buy, editing a row's type into a buy, or increasing an existing buy's amount are
      rejected with a ledger error. Enforcement lives in `portfolio/ledger.py`
      (`create_transaction`/`update_transaction`, `DELISTED_BUY_MESSAGE`), the single
      chokepoint for both create and edit; read-path `coin__is_active=True` filters
      were relaxed in `portfolio/models.py`, `portfolio/services.py`, and
      `portfolio/ledger.py`, and the create/delete views no longer gate coin lookup on
      `is_active`. No migration (the field already exists; soft-deactivate never
      deletes rows). Note: this deliberately diverges from a possible future 13.4
      "transactions are immutable audit records" ruling — the product owner chose
      closability over immutability.
    - 11.7 ✅ Consider a user-entered trade timestamp separate from `created`.
      **Decision (product owner): Option B — a display-only, date-only `trade_date`.**
      `PortfolioTransaction.trade_date` is a `DateField(default=timezone.localdate)`
      (non-null), surfaced and sortable in the transaction lists ("Trade date"
      column; `created` stays as a separate "Entered" column). It is user-entered
      on the create/edit form (HTML5 `type="date"`, defaults to today, `clean_trade_date`
      rejects future dates; forgiving — an omitted value falls back to today) and
      threaded through `portfolio.ledger.create_transaction`/`update_transaction`
      purely as a persisted value. **FIFO/ledger ordering was deliberately NOT
      touched:** `build_holdings` and the ledger feasibility replay
      (`_ordered_rows`/`_locked_rows`) still order by `(created, id)`, so 10.8's
      determinism and all feasibility invariants are preserved and `trade_date`
      has zero effect on cost basis, P/L, or oversell checks. `DEFAULT_SORT` moved
      to `trade_date` (display-only list sort; `created` kept in `ALLOWED_SORTS`).
      Migration `0004` is hand-split (AddField null=True → RunPython backfill
      `trade_date` from the local date of each row's `created` → AlterField to
      non-null with the localdate default) so existing rows keep their historical
      order instead of collapsing to today. **Option C (trade_date authoritative
      for FIFO/ledger ordering) was deliberately deferred** — it would reopen the
      user-perturbable replay ordering that 10.8 closed and require full ledger
      re-validation on every date edit; not warranted without an explicit
      backdated-cost-basis requirement.
    - 11.8 ✅ Add indexes for common queries such as `(user, coin, created)` and
      `(user, created)`. **Decision: exactly two composite indexes** on
      `PortfolioTransaction.Meta.indexes` (migration `0005`, pure `AddIndex`, no
      data change):
      - `pf_txn_user_coin_created` = `Index(fields=["user","coin","created"])` —
        the workhorse. Equality prefix `(user, coin)` then the FIFO-authoritative
        trailing `created`. Serves the ledger `FOR UPDATE` lock path
        (`_locked_rows`, the lock-contention-critical query), `build_holdings`
        (`user` + `coin_id__in`), and `get_coin_balance` / per-coin transaction
        lists (via the `(user, coin)` prefix). Trailing col is `created`, NOT
        `trade_date`, matching 10.8 replay determinism.
      - `pf_txn_user_trade_date` = `Index(fields=["user","trade_date"])` — the
        default ordering of the transaction lists.
      **Deliberate divergence from the task text:** the second index is
      `(user, trade_date)` rather than the literally-suggested `(user, created)`,
      because step 11.7 changed `DEFAULT_SORT` to `trade_date`. `(user, created)`
      would only serve the now-non-default "sort by created" on the full list, so
      it was dropped in favor of the composite that matches the actual default
      sort. **Deliberately NOT added** (redundant / low-value): plain `(user, coin)`
      (leftmost prefix of index 1); `(user, created)` (non-default sort); and any
      index for the `type`/`amount`/`price`/`total`/`coin__name` list sorts
      (`type` non-selective; per-user row counts tiny so secondary sorts are
      trivial; `total` is a computed annotation; `coin__name` is a cross-table
      sort no single-table index can serve). Single-column `user_id`/`coin_id`
      btree indexes already exist (Django FK defaults). `CREATE INDEX` is
      non-concurrent (brief write lock) — fine at this app's per-user-ledger size;
      `AddIndexConcurrently` exists but is not needed. A model test pins the
      exact index set (`test_meta_indexes_are_the_two_expected_composites`).

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
