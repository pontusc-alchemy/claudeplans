"""The swappable identity seam: who is making this request.

CurrentUser is the resolved caller. The provider is a dependency so the
implementation swaps without touching call sites: the dev no-op provider returns
one fixed trusted user; the cloud migration drops in an IAP provider that
validates `x-goog-iap-jwt-assertion`. main.py selects the provider from AUTH_MODE
(fail-closed). Real uuid5 identity minting lives in identity.py + registry.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The resolved caller: a stable uid plus the human-facing name/namespace."""

    uid: str
    name: str
    namespace: str


class UserProvider(Protocol):
    """Resolves the current user for a request. Implementations swap by AUTH_MODE.

    Providers receive the request headers (not FastAPI types) so the IAP provider
    can read the JWT assertion while the seam stays free of web-stack coupling.
    """

    async def __call__(self, headers: Mapping[str, str]) -> CurrentUser: ...


# Dev/local only: the trusted user when CLAUDEPLANS_NOOP_UID is unset. namespace ==
# uid, so write-own targets /v1/users/dev/...; fail-closed forbids a cloud backend.
DEV_UID = "dev"
DEV_USER: CurrentUser = CurrentUser(uid=DEV_UID, name=DEV_UID, namespace=DEV_UID)


class NoopProvider:
    """Returns one fixed trusted user, built from `uid`. Dev/local only.

    The principal is configurable so a local stack can serve as the machine's own
    user instead of a shared "dev". That is what lets a CLI deriving its uid from the
    host write at all, since write-own compares the two. Settings charset-validates
    the uid, so an illegal one never reaches this constructor.
    """

    def __init__(self, uid: str = DEV_UID) -> None:
        self._user = CurrentUser(uid=uid, name=uid, namespace=uid)

    async def __call__(self, headers: Mapping[str, str]) -> CurrentUser:
        return self._user


class IapProvider:
    """Validates `x-goog-iap-jwt-assertion`, maps the verified identity to a uid.

    The verified identity is resolved to (or registered on first sight in) the
    UserRegistry, and the caller is returned as a CurrentUser whose namespace == uid
    (write-own). Deferred to the cloud migration: the JWT-validation/registry wiring
    is documented intent only and not yet implemented.
    """

    async def __call__(self, headers: Mapping[str, str]) -> CurrentUser:
        raise NotImplementedError(
            "IAP provider is deferred to the cloud migration; "
            "run with AUTH_MODE=noop for local use"
        )
