"""Composition root: build the FastAPI app, wire dependencies, fail-closed at startup.

Routers, the events feed, the search index, and the render cache are wired here as
later phases add them. For now this assembles a runnable app so the serve image
has a PID-1 target. A SINGLE uvicorn worker is required (in-process events feed +
in-memory index); multi-worker is deferred behind a shared broker.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import install
from .auth.provider import IapProvider, NoopProvider, UserProvider
from .config import AuthMode, Settings, fail_closed_check, load_settings
from .storage.filesystem import FilesystemRepository


def select_provider(settings: Settings) -> UserProvider:
    """Pick the identity provider for the configured AUTH_MODE.

    The default is iap (see config.Settings.auth_mode), whose provider is DEFERRED:
    IapProvider raises NotImplementedError, so an unconfigured iap deployment fails
    closed by refusing every write with a per-request error rather than serving one
    unauthenticated. Local use requires AUTH_MODE=noop.
    """
    match settings.auth_mode:
        case AuthMode.noop:
            return NoopProvider()
        case AuthMode.iap:
            return IapProvider()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: later phases build the search index and subscribe the cache/SSE here.
    # Graceful SIGTERM handling for open SSE generators is wired in the rendering phase.
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Fail closed before serving any request."""
    settings = settings or load_settings()
    fail_closed_check(settings)
    app = FastAPI(
        title="claudeplans",
        version="0.1.0",
        lifespan=lifespan,
        description="Structured CRUD plan service. Interactive API docs at /docs.",
    )
    # Build the repo and stash settings/repo on app.state so the dependency
    # accessors hand them to routes; then mount the API.
    app.state.settings = settings
    app.state.repo = FilesystemRepository(settings.filesystem.root)
    app.state.user_provider = select_provider(settings)
    install(app)
    return app


app = create_app()
