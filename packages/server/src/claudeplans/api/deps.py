"""Request-scoped dependencies and the If-Match precondition helper.

The repository and settings are built once at startup and stashed on app.state;
these accessors hand them to routes via Depends without a module-level global.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from ..auth.provider import CurrentUser, UserProvider
from ..auth.registry import UserRegistry
from ..config import Settings
from ..events import EventFeed
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


def require_if_match(
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> str:
    """Return the rev from the If-Match header, or 428 if absent.

    Index-addressed and destructive ops use optimistic concurrency, so the caller
    MUST pass the rev it last saw. HTTP ETags are quoted, so strip the surrounding
    double-quotes before handing the bare rev to core.
    """
    if if_match is None:
        raise HTTPException(status_code=428, detail="If-Match header required")
    return if_match.strip('"')


# Annotated aliases so routes inject via a parameter annotation (the modern FastAPI
# form) rather than a Depends() call in a default — the latter trips ruff B008.
RepoDep = Annotated[Repository, Depends(get_repo)]
FeedDep = Annotated[EventFeed, Depends(get_feed)]
SearchIndexDep = Annotated[SearchIndex, Depends(get_search_index)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IfMatchDep = Annotated[str, Depends(require_if_match)]
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
RegistryDep = Annotated[UserRegistry, Depends(get_registry)]
