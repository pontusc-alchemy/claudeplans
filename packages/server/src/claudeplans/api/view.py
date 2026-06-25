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

from claudeplans_contracts import NotFound, document_key
from claudeplans_contracts.dto import LineageResponse

from .. import core, templates
from ..cache import FragmentCache
from ..events import EventFeed
from ..lineage import build_lineage
from .deps import RepoDep

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


@router.get("/v1/users/{uid}/projects/{project}/docs/{slug}/view")
async def view_document(
    uid: str, project: str, slug: str, repo: RepoDep
) -> HTMLResponse:
    """Render the full document page (the live-view morph target)."""
    key = document_key(uid, project, slug)
    _, doc = await core.get_document(repo, key)
    html = templates.render_page(doc, events_url=_events_url(uid, project, slug))
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
async def project_lineage(uid: str, project: str, repo: RepoDep) -> HTMLResponse:
    """Render the lineage index for one user+project."""
    # Trailing slash scopes to the project segment exactly: validate_key_segment
    # forbids slashes in a segment, so "uid/project/" can't match a sibling.
    prefix = f"{uid}/{project}/"
    docs = []
    for entry in await repo.list(prefix):
        # ListEntry.metadata lacks the ref fields, so load each full Document via the
        # same parse path core.get_document uses rather than re-implementing it.
        _, doc = await core.get_document(repo, entry.key)
        docs.append(doc)
    lineage = build_lineage(docs)
    html = templates.render_lineage_page(
        lineage,
        title=f"{project} · lineage",
        view_url=lambda slug: _view_url(uid, project, slug),
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP})


@router.get("/v1/users/{uid}/projects/{project}/lineage")
async def project_lineage_json(
    uid: str, project: str, repo: RepoDep
) -> LineageResponse:
    """Return the lineage tree for one user+project as plain JSON."""
    prefix = f"{uid}/{project}/"
    docs = []
    for entry in await repo.list(prefix):
        _, doc = await core.get_document(repo, entry.key)
        docs.append(doc)
    lineage = build_lineage(docs)
    return LineageResponse.model_validate(dataclasses.asdict(lineage))
