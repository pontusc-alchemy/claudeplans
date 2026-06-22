"""The swappable identity seam: who is making this request.

CurrentUser is the resolved caller. The provider is a dependency so the
implementation swaps without touching call sites: the dev no-op provider returns
one fixed trusted user; the cloud migration drops in an IAP provider that
validates `x-goog-iap-jwt-assertion`. main.py selects the provider from AUTH_MODE
(fail-closed). Real uuid5 identity minting lands in the auth phase.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The resolved caller: a stable uid plus the human-facing name/namespace."""

    uid: str
    name: str
    namespace: str


class UserProvider(Protocol):
    """Resolves the current user for a request. Implementations swap by AUTH_MODE."""

    async def __call__(self) -> CurrentUser: ...


# Dev/local only: a single fixed trusted user. The fail-closed check forbids
# pairing this with a cloud backend.
DEV_USER: CurrentUser = CurrentUser(
    uid="00000000-0000-0000-0000-000000000000",
    name="dev",
    namespace="dev",
)


class NoopProvider:
    """Returns the fixed DEV_USER. Dev/local only."""

    async def __call__(self) -> CurrentUser:
        return DEV_USER
