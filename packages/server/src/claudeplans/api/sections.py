"""Section routes — thin over core.py.

Section ops address by stable anchor and set absolute values (or a merge patch),
so they are re-apply-safe and need no client rev.
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    AddSectionRequest,
    MoveSectionRequest,
    PatchSectionRequest,
    SetSectionRequest,
    document_key,
)

from .. import core
from ..events import Event
from .deps import CurrentUserDep, FeedDep, IfMatchDep, RepoDep
from .envelope import ResponseEnvelope, envelope

router = APIRouter(
    prefix="/v1/users/{uid}/projects/{project}/docs/{slug}/sections",
    tags=["sections"],
)


@router.post("")
async def add_section(
    uid: str,
    project: str,
    slug: str,
    body: AddSectionRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.add_section(
        repo,
        key,
        body.anchor,
        body.heading,
        body.body,
        body.level,
        body.placement,
        body.at,
        user=user,
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"sections.{body.anchor}")


@router.post("/{anchor}/move")
async def move_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    body: MoveSectionRequest,
    response: Response,
    expected_rev: IfMatchDep,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    # Reorders the section list, so it carries the client's rev (missing -> 428,
    # stale -> 409), consistent with move_phase.
    key = document_key(uid, project, slug)
    rev, doc = await core.move_section(
        repo, key, anchor, body.to_index, expected_rev, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc)


@router.put("/{anchor}")
async def set_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    body: SetSectionRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_section(
        repo,
        key,
        anchor,
        body.heading,
        body.body,
        body.level,
        body.placement,
        user=user,
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"sections.{anchor}")


@router.patch("/{anchor}")
async def patch_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    body: PatchSectionRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.patch_section(repo, key, anchor, body.patch, user=user)
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"sections.{anchor}")


@router.delete("/{anchor}")
async def remove_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    # Returns 200 + envelope, not 204: the mutated document is in the response body.
    key = document_key(uid, project, slug)
    rev, doc = await core.remove_section(repo, key, anchor, user=user)
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"sections.{anchor}")
