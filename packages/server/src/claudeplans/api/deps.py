"""Request-scoped dependencies and the If-Match precondition helper.

The repository and settings are built once at startup and stashed on app.state;
these accessors hand them to routes via Depends without a module-level global.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from claudeplans_contracts import validate_rev

from ..auth.provider import CurrentUser, UserProvider
from ..auth.registry import UserRegistry
from ..config import Settings
from ..events import EventFeed
from ..projects import ProjectRegistry
from ..search import SearchIndex
from ..storage.repository import Repository


def get_repo(request: Request) -> Repository:
    """The process-wide repository, built at startup."""
    return request.app.state.repo


def get_feed(request: Request) -> EventFeed:
    """The process-wide change feed, built at startup."""
    return request.app.state.feed


def get_search_index(request: Request) -> SearchIndex:
    """The process-wide search index, built at startup and kept fresh via the feed."""
    return request.app.state.search_index


async def get_current_user(request: Request) -> CurrentUser:
    """Resolve the caller via the configured provider (selected by AUTH_MODE)."""
    provider: UserProvider = request.app.state.user_provider
    return await provider(request.headers)


def get_settings(request: Request) -> Settings:
    """The loaded settings, built at startup."""
    return request.app.state.settings


def get_registry(request: Request) -> UserRegistry:
    """The process-wide user registry, built at startup."""
    return request.app.state.registry


def get_project_registry(request: Request) -> ProjectRegistry:
    """The process-wide project display-name registry, built at startup."""
    return request.app.state.project_registry


def require_if_match(
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> str:
    """Return the rev from the If-Match header, or 428 if absent.

    Index-addressed and destructive ops use optimistic concurrency, so the caller
    MUST pass the rev it last saw. HTTP ETags are quoted, so strip the surrounding
    double-quotes before handing the bare rev to core. Validated via `validate_rev`
    so a malformed rev raises InvalidRev (-> 400) instead of falling through to a
    StaleRevision comparison.
    """
    if if_match is None:
        raise HTTPException(status_code=428, detail="If-Match header required")
    return validate_rev(if_match.strip('"'))


def require_optional_if_match(
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> str | None:
    """Return the rev from If-Match, or None if absent — for routes where the
    conditional applies only to some code paths (core enforces it there).

    Validated via `validate_rev` when present, for the same reason as
    `require_if_match`.
    """
    return validate_rev(if_match.strip('"')) if if_match is not None else None


# Annotated aliases so routes inject via a parameter annotation (the modern FastAPI
# form) rather than a Depends() call in a default — the latter trips ruff B008.
RepoDep = Annotated[Repository, Depends(get_repo)]
FeedDep = Annotated[EventFeed, Depends(get_feed)]
SearchIndexDep = Annotated[SearchIndex, Depends(get_search_index)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IfMatchDep = Annotated[str, Depends(require_if_match)]
OptionalIfMatchDep = Annotated[str | None, Depends(require_optional_if_match)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
RegistryDep = Annotated[UserRegistry, Depends(get_registry)]
ProjectRegistryDep = Annotated[ProjectRegistry, Depends(get_project_registry)]
