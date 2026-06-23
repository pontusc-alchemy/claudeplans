"""Composition root: build the FastAPI app, wire dependencies, fail-closed at startup.

Routers, the in-process events feed, and the render cache are wired here; the search
index is a later phase. A SINGLE uvicorn worker is required (in-process events feed +
in-memory cache); multi-worker is deferred behind a shared broker.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api import install
from .auth.provider import IapProvider, NoopProvider, UserProvider
from .cache import FragmentCache
from .config import AuthMode, Settings, fail_closed_check, load_settings
from .events import EventFeed
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
    # The feed/cache are built in create_app (so app.state always has them, even in
    # unit tests that never enter lifespan); here we only close the feed on shutdown.
    # In production the __main__ Server subclass closes the feed at shutdown START so
    # SSE generators drain in time; this `finally` is the idempotent backstop for
    # non-uvicorn teardown (tests).
    try:
        yield
    finally:
        app.state.feed.close()


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
    # Built here (not only in lifespan) so app.state always carries them — unit tests
    # drive routes without entering lifespan; lifespan's shutdown half closes the feed.
    app.state.feed = EventFeed()
    app.state.render_cache = FragmentCache()
    install(app)
    # Vendored CSS/JS (htmx, idiomorph, htmx-ext-sse) served same-origin so the
    # strict CSP (`script-src 'self'`) admits them.
    app.mount(
        "/assets",
        StaticFiles(directory=Path(__file__).parent / "assets"),
        name="assets",
    )
    return app


app = create_app()
