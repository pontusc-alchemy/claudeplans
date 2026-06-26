"""Live-view routes: the HTML page, its SSE stream, and the project lineage index.

Read-only (GET) and open to all — reads are unrestricted in the auth model, so
these depend on the repo (+ the app's feed/cache via app.state) but enforce no
can_write. The page is a single morph target; the SSE stream pushes a freshly
rendered, sanitized doc body on connect (snapshot-on-connect = reconnect resync)
and again on every matching change Event. A strict CSP (`script-src 'self'`, no
`unsafe-eval`) is set on the HTML responses so only the vendored, same-origin
scripts can run.
"""

import dataclasses
from collections.abc import AsyncIterator
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import ValidationError

from claudeplans_contracts import NotFound, document_key
from claudeplans_contracts.dto import LineageResponse
from claudeplans_contracts.errors import PlanError

from .. import core, navigation, templates
from ..auth.registry import UserRegistry
from ..cache import FragmentCache
from ..events import EventFeed
from ..storage.repository import Repository
from .deps import CurrentUserDep, RegistryDep, RepoDep

router = APIRouter(tags=["view"])

# Default-deny CSP: only same-origin scripts/styles, images from self or data: URIs,
# and same-origin connect() (the SSE EventSource). No 'unsafe-eval'/'unsafe-inline'.
CSP: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'"
)


def _events_url(uid: str, project: str, slug: str) -> str:
    return f"/v1/users/{uid}/projects/{project}/docs/{slug}/events"


def _view_url(uid: str, project: str, slug: str) -> str:
    return f"/v1/users/{uid}/projects/{project}/docs/{slug}/view"


def _project_url(uid: str, project: str) -> str:
    return f"/v1/users/{uid}/projects/{project}/"


def _user_url(uid: str) -> str:
    return f"/v1/users/{uid}/"


async def _build_sidebar(
    repo: Repository,
    registry: UserRegistry,
    uid: str,
    project: str | None,
    slug: str | None,
) -> dict[str, object]:
    """Assemble the sidebar context for `uid`'s tree, marking the open doc active."""
    projects = await navigation.build_user_tree(repo, uid)
    users = await navigation.list_users(repo, registry, uid)
    return templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid=uid,
        current_project=project,
        current_slug=slug,
        view_url=lambda p, s: _view_url(uid, p, s),
        lineage_url=lambda p: _project_url(uid, p),
    )


def _sse_frame(html: str) -> str:
    """Format `html` as one SSE `message` event.

    Each HTML line gets its own `data:` field (SSE concatenates them with newlines)
    and the frame ends with a blank line. The explicit `event: message` matches the
    template's `sse-swap="message"`.
    """
    data = "\n".join(f"data: {line}" for line in html.splitlines())
    return f"event: message\n{data}\n\n"


_DELETED_FRAME: Final = _sse_frame(
    '<p class="doc-removed">This document was removed.</p>'
)

_UNAVAILABLE_FRAME: Final = _sse_frame(
    '<p class="doc-removed">This document is currently unavailable.</p>'
)


@router.get("/v1/users/{uid}/projects/{project}/docs/{slug}/view")
async def view_document(
    uid: str, project: str, slug: str, repo: RepoDep, registry: RegistryDep
) -> HTMLResponse:
    """Render the full document page (the live-view morph target)."""
    key = document_key(uid, project, slug)
    _, doc = await core.get_document(repo, key)
    sidebar = await _build_sidebar(repo, registry, uid, project, slug)
    html = templates.render_page(
        doc, events_url=_events_url(uid, project, slug), sidebar=sidebar
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP})


@router.get("/v1/users/{uid}/projects/{project}/docs/{slug}/events")
async def document_events(
    uid: str, project: str, slug: str, request: Request
) -> StreamingResponse:
    """Stream the doc body: a snapshot on connect, then one frame per change."""
    repo = request.app.state.repo
    feed: EventFeed = request.app.state.feed
    cache: FragmentCache = request.app.state.render_cache
    key = document_key(uid, project, slug)

    async def stream() -> AsyncIterator[str]:
        # Register the subscription BEFORE the snapshot so an Event published in the
        # window between snapshot-render and first iteration is queued, not lost (it
        # surfaces as a harmless redundant frame — the morph is idempotent).
        with feed.subscribe() as sub:
            # Snapshot-on-connect: render current state first so a (re)connecting
            # client resyncs without any event replay.
            try:
                rev, doc = await core.get_document(repo, key)
            except NotFound:
                yield _DELETED_FRAME
                return
            except PlanError, ValidationError:
                # A doc can become corrupt or fail body validation after an edit
                # (or a legacy body the current model rejects). The stream has
                # already sent headers, so a raise here would tear the connection
                # — degrade to an "unavailable" frame instead, mirroring the
                # poison-skip used by the lineage views.
                yield _UNAVAILABLE_FRAME
                return
            yield _sse_frame(
                cache.get_or_render(key, rev, lambda: templates.render_doc_body(doc))
            )
            # Then live updates. The subscription ends on the shutdown sentinel: the
            # __main__ Server subclass closes the feed at shutdown START, so this
            # generator (and the response) completes before the bounded graceful
            # timeout instead of being force-cancelled at the deadline.
            async for event in sub:
                if event.key != key:
                    continue
                try:
                    rev, doc = await core.get_document(repo, key)
                except NotFound:
                    yield _DELETED_FRAME
                    return
                except PlanError, ValidationError:
                    # Same poison tolerance as the snapshot read.
                    yield _UNAVAILABLE_FRAME
                    return
                yield _sse_frame(
                    cache.get_or_render(
                        key, rev, lambda doc=doc: templates.render_doc_body(doc)
                    )
                )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/v1/users/{uid}/projects/{project}/")
async def project_lineage(
    uid: str, project: str, repo: RepoDep, registry: RegistryDep
) -> HTMLResponse:
    """Render the lineage index for one user+project."""
    lineage = await navigation.load_project_lineage(repo, uid, project)
    sidebar = await _build_sidebar(repo, registry, uid, project, None)
    html = templates.render_lineage_page(
        lineage,
        title=project,
        view_url=lambda slug: _view_url(uid, project, slug),
        sidebar=sidebar,
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP})


@router.get("/v1/users/{uid}/")
async def user_landing(uid: str, repo: RepoDep, registry: RegistryDep) -> HTMLResponse:
    """Landing page for a user: the sidebar chrome plus a minimal welcome pane."""
    sidebar = await _build_sidebar(repo, registry, uid, None, None)
    html = templates.render_landing_page(title=f"{uid} · plans", sidebar=sidebar)
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP})


@router.get("/")
async def root(
    repo: RepoDep, registry: RegistryDep, current_user: CurrentUserDep
) -> HTMLResponse:
    """The site root: a user picker listing everyone who has plans."""
    users = await navigation.list_users(repo, registry, current_user.uid)
    html = templates.render_user_picker(title="plans", users=users, user_url=_user_url)
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP})


@router.get("/v1/users/{uid}/projects/{project}/lineage")
async def project_lineage_json(
    uid: str, project: str, repo: RepoDep
) -> LineageResponse:
    """Return the lineage tree for one user+project as plain JSON."""
    lineage = await navigation.load_project_lineage(repo, uid, project)
    return LineageResponse.model_validate(dataclasses.asdict(lineage))
