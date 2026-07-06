"""Structured errors raised by the portfolio ledger domain service.

Views catch ``LedgerError`` to translate an invalid ledger mutation into a
form error (create/edit) or a user message (delete). Kept in a dedicated
module (not ``portfolio/ledger.py``) so consumers can import the catch target
without pulling in the mutation module.
"""


class LedgerError(Exception):
    """A ledger mutation would leave the coin balance negative at some point."""
