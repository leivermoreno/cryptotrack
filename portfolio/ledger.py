"""Portfolio ledger domain service.

Owns the ledger invariants for create/edit/delete of ``PortfolioTransaction``
rows. Every mutation is validated by a single *feasibility replay*: project the
proposed change onto the user's existing rows for that coin, replay the running
balance in deterministic ``(trade_date, id)`` order, and reject
(``LedgerError``) the instant the balance goes negative -- an oversell at any
point, not just the final balance. This one mechanism covers create-sell over
balance, edit-aware sell edits, and buy edits/deletes that later sells depend
on.

Views stay thin: call the service, translate ``LedgerError`` into a form error
(create/edit) or a user message (delete).
"""

from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from portfolio.exceptions import LedgerError
from portfolio.models import PortfolioTransaction

# Shown for a create/edit that would oversell (the coordinator-pinned wording;
# 10.4/10.5 harden this path but keep the text).
OVERSELL_MESSAGE = "Insufficient balance to sell this amount."

# Shown when a mutation would acquire more of a delisted (is_active=False) coin:
# a new buy, an edit turning a row into a buy, or an edit increasing a buy's
# amount. Selling, reducing/price-only buy edits, and deletes stay allowed so
# the user can close or adjust a dead position (step 11.6, Option C).
DELISTED_BUY_MESSAGE = "Cannot buy or increase a position in a delisted coin."
# Unsaved creates should sort after existing same-date rows, matching the
# auto-increment id they will receive after validation.
NEW_ROW_TIEBREAKER_ID = 2**63 - 1


def _ordered_rows(user, coin):
    """Existing rows for user/coin in replay order."""
    return list(
        PortfolioTransaction.objects.filter(user=user, coin=coin)
        .order_by("trade_date", "id")
        .values_list("id", "type", "amount", "trade_date")
    )


def _locked_rows(user, coin):
    """Same as ``_ordered_rows`` but locks the matched ledger rows.

    ``select_for_update(of=("self",))`` takes a row-level ``FOR UPDATE`` on the
    ``PortfolioTransaction`` rows only -- scoped via ``of=`` so the joined
    ``Coin`` row is *not* locked and does not contend with the catalog sync that
    rewrites ``Coin`` on an interval. Must run inside ``transaction.atomic()``.
    """
    return list(
        PortfolioTransaction.objects.filter(user=user, coin=coin)
        .select_for_update(of=("self",))
        .order_by("trade_date", "id")
        .values_list("id", "type", "amount", "trade_date")
    )


def _timeline_entry(row_id, tx_type, amount, trade_date):
    return {
        "id": row_id,
        "type": tx_type,
        "amount": amount,
        "trade_date": trade_date,
    }


def _replay_feasible(entries):
    """True if the running balance never goes negative over ``entries``.

    ``entries`` is an iterable of timeline entries. They are sorted here so
    updates that change ``trade_date`` are validated in their new slot.
    """
    balance = Decimal("0")
    for entry in sorted(entries, key=lambda row: (row["trade_date"], row["id"])):
        tx_type = entry["type"]
        amount = entry["amount"]
        if tx_type == "buy":
            balance += amount
        else:
            balance -= amount
        if balance < 0:
            return False
    return True


def create_transaction(*, user, coin, type, amount, price, trade_date=None):
    """Validate and persist a new transaction; raise ``LedgerError`` if infeasible.

    ``trade_date`` is the user-entered trade date and is the authoritative FIFO
    replay key. ``None`` uses today's date, matching the model default.
    """
    # A delisted coin can be sold/closed but not bought (11.6, Option C).
    if type == "buy" and not coin.is_active:
        raise LedgerError(DELISTED_BUY_MESSAGE)
    with db_transaction.atomic():
        # Lock this user/coin's existing ledger rows, then replay-and-save under
        # the same transaction so a concurrent sell can't pass its check against
        # a balance we're about to consume. Empty-ledger first writes lock no
        # rows, but that's invariant-safe: concurrent first-buys only add
        # balance, and concurrent first-sells both reject at balance 0 -- so no
        # parent lock-anchor is needed.
        effective_trade_date = trade_date or timezone.localdate()
        projected = [
            _timeline_entry(row_id, row_type, row_amount, row_trade_date)
            for row_id, row_type, row_amount, row_trade_date in _locked_rows(user, coin)
        ]
        projected.append(
            _timeline_entry(NEW_ROW_TIEBREAKER_ID, type, amount, effective_trade_date)
        )
        if not _replay_feasible(projected):
            raise LedgerError(OVERSELL_MESSAGE)
        return PortfolioTransaction.objects.create(
            user=user,
            coin=coin,
            type=type,
            amount=amount,
            price=price,
            trade_date=effective_trade_date,
        )


def update_transaction(*, transaction, type, amount, price, trade_date=None):
    """Validate and persist an edit; raise ``LedgerError`` if infeasible.

    Edit-aware: the edited row is replaced in the projected timeline, so its old
    values do not leak into the replay (10.4), and reducing a buy below what
    later sells consumed is rejected (10.5).

    ``trade_date`` participates in the replay; ``None`` leaves the row's
    existing trade_date unchanged.
    """
    with db_transaction.atomic():
        # Lock the user/coin ledger rows before replaying the edit so it is
        # serialized against concurrent sells (see create_transaction for the
        # empty-ledger safety note).
        projected = []
        old_type = old_amount = None
        for row_id, row_type, row_amount, row_trade_date in _locked_rows(
            transaction.user, transaction.coin
        ):
            if row_id == transaction.id:
                # DB (pre-edit) values: the ModelForm has already mutated the
                # in-memory ``transaction`` instance to the new type/amount, so
                # the delisted guard below reads the old values from here.
                old_type, old_amount = row_type, row_amount
                projected.append(
                    _timeline_entry(
                        row_id,
                        type,
                        amount,
                        trade_date if trade_date is not None else row_trade_date,
                    )
                )
            else:
                projected.append(
                    _timeline_entry(row_id, row_type, row_amount, row_trade_date)
                )
        # On a delisted coin the user may correct or reduce an existing buy and
        # may sell, but may not acquire more: reject turning a non-buy into a
        # buy, and reject increasing a buy's amount (11.6, Option C).
        if (
            type == "buy"
            and not transaction.coin.is_active
            and old_type is not None
            and (old_type != "buy" or amount > old_amount)
        ):
            raise LedgerError(DELISTED_BUY_MESSAGE)
        if not _replay_feasible(projected):
            raise LedgerError(OVERSELL_MESSAGE)
        transaction.type = type
        transaction.amount = amount
        transaction.price = price
        if trade_date is not None:
            transaction.trade_date = trade_date
        transaction.save()
        return transaction


def delete_transaction(*, transaction):
    """Validate and delete a transaction; raise ``LedgerError`` if infeasible.

    Deleting a buy that later sells depended on would drive the balance
    negative and is rejected.
    """
    with db_transaction.atomic():
        # Lock the user/coin ledger rows before replaying the delete so it is
        # serialized against concurrent sells (see create_transaction for the
        # empty-ledger safety note).
        projected = [
            _timeline_entry(row_id, row_type, row_amount, row_trade_date)
            for row_id, row_type, row_amount, row_trade_date in _locked_rows(
                transaction.user, transaction.coin
            )
            if row_id != transaction.id
        ]
        if not _replay_feasible(projected):
            raise LedgerError(
                "Deleting this buy transaction would make your balance negative."
            )
        transaction.delete()
