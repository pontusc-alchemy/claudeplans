"""The pure authorization predicate — no web stack, unit-testable in isolation.

Policy: a user may write only within their own namespace (write-own). Kept pure
so it is trivially testable and reused by every write path.
"""

from .provider import CurrentUser


def can_write(user: CurrentUser, namespace: str) -> bool:
    """Return True iff `user` may write in `namespace` (write-own)."""
    return user.namespace == namespace
