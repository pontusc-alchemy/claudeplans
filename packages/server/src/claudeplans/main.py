"""Composition root: build the FastAPI app, wire dependencies, fail-closed at startup.

Routers, the in-process events feed, and the render cache are wired here; the search
index is a later phase. A SINGLE uvicorn worker is required (in-process events feed +
in-memory cache); multi-worker is deferred behind a shared broker.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from .api import install
from .api.limits import BodySizeLimitMiddleware
from .auth.provider import IapProvider, NoopProvider, UserProvider
from .auth.registry import UserRegistry
from .cache import FragmentCache
from .config import AuthMode, Settings, fail_closed_check, load_settings
from .events import EventFeed
from .search import SearchIndex
from .storage.filesystem import FilesystemRepository


class _NoCacheStaticFiles(StaticFiles):
    """Serve assets with `Cache-Control: no-cache` so the browser revalidates via
    ETag on every load — a redeploy's new CSS/JS shows up without a manual hard
    refresh, while unchanged files still return 304."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
    # The feed/cache/index are built in create_app (so app.state always has them, even
    # in unit tests that never enter lifespan). Here we start the search index's
    # background consumer — it builds from storage then keeps fresh off the feed — and
    # await the initial build so the first request searches a complete index. On
    # shutdown we close the feed (in production the __main__ Server subclass closes it
    # at shutdown START so SSE generators drain in time; this is the idempotent backstop
    # for non-uvicorn teardown), which ends the consumer loop, then await its exit.
    index: SearchIndex = app.state.search_index
    index_task = asyncio.create_task(index.run(app.state.repo, app.state.feed))
    try:
        await index.ready()
        yield
    finally:
        app.state.feed.close()
        await index_task


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
    # User registry (display names for the switcher). Path is OUTSIDE the storage
    # root so the repository's *.json walk never treats it as a document.
    app.state.registry = UserRegistry(Path(settings.registry_path))
    # Built here (not only in lifespan) so app.state always carries them — unit tests
    # drive routes without entering lifespan; lifespan's shutdown half closes the feed.
    app.state.feed = EventFeed()
    app.state.render_cache = FragmentCache()
    app.state.search_index = SearchIndex()
    install(app)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    # Vendored CSS/JS (htmx, idiomorph, htmx-ext-sse) served same-origin so the
    # strict CSP (`script-src 'self'`) admits them.
    app.mount(
        "/assets",
        _NoCacheStaticFiles(directory=Path(__file__).parent / "assets"),
        name="assets",
    )
    return app


app = create_app()
