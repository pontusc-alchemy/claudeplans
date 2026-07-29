"""Document-lifecycle routes — thin over core.py.

Every route builds the storage key from the path identity, calls the matching
core function, mirrors the returned rev into the ETag header, and returns the
{data, warnings[]} envelope.
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    DocStatusRequest,
    DocumentCreate,
    ResearchRefsRequest,
    SetDocumentMetaRequest,
    document_key,
)

from .. import core
from ..events import Event
from .deps import CurrentUserDep, FeedDep, IfMatchDep, RenderCacheDep, RepoDep
from .envelope import ResponseEnvelope, envelope

router = APIRouter(prefix="/v1/users/{uid}/projects/{project}/docs", tags=["documents"])


@router.head("/{slug}")
async def head(
    uid: str,
    project: str,
    slug: str,
    response: Response,
    repo: RepoDep,
) -> Response:
    """Return the current ETag (rev) for a document without a body."""
    key = document_key(uid, project, slug)
    rev, _ = await core.get_document(repo, key)
    return Response(status_code=200, headers={"ETag": rev})


@router.post("", status_code=201)
async def create(
    uid: str,
    project: str,
    body: DocumentCreate,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    rev, doc = await core.create_document(
        repo, owner_id=uid, project=project, doc_in=body, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=document_key(uid, project, body.slug), rev=rev))
    return envelope(doc)


@router.get("/{slug}")
async def get(
    uid: str,
    project: str,
    slug: str,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.get_document(repo, key)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.delete("/{slug}", status_code=204)
async def delete(
    uid: str,
    project: str,
    slug: str,
    expected_rev: IfMatchDep,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
    render_cache: RenderCacheDep,
) -> Response:
    key = document_key(uid, project, slug)
    await core.delete_document(repo, key, expected_rev, user=user)
    # A re-created doc restarts revs at "1", which would collide with a dead
    # incarnation's cached entries at the same rev — drop them all now.
    render_cache.invalidate(key)
    # No new rev for a delete; a viewer's SSE reloads at expected_rev -> NotFound ->
    # the deleted frame.
    feed.publish(Event(key=key, rev=expected_rev))
    return Response(status_code=204)


@router.put("/{slug}")
async def set_document_meta(
    uid: str,
    project: str,
    slug: str,
    body: SetDocumentMetaRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_document_meta(
        repo,
        key,
        title=body.title,
        description=body.description,
        date=body.date,
        frontmatter=body.frontmatter,
        clear_description=body.clear_description,
        clear_date=body.clear_date,
        user=user,
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc)


@router.put("/{slug}/status")
async def set_status(
    uid: str,
    project: str,
    slug: str,
    body: DocStatusRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_document_status(repo, key, body.status, user=user)
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc)


@router.put("/{slug}/research-refs")
async def set_research_refs(
    uid: str,
    project: str,
    slug: str,
    body: ResearchRefsRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.put_research_refs(
        repo, key, body.research_refs, body.primary_parent_ref, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc)
