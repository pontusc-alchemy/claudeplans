"""Section routes — thin over core.py.

Section ops address by stable anchor and set absolute values (or a merge patch),
so they are re-apply-safe and need no client rev.
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    AddSectionRequest,
    PatchSectionRequest,
    SetSectionRequest,
    document_key,
)

from .. import core
from .deps import RepoDep
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
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.add_section(
        repo, key, body.anchor, body.heading, body.body, body.level
    )
    response.headers["ETag"] = rev
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
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_section(
        repo, key, anchor, body.heading, body.body, body.level
    )
    response.headers["ETag"] = rev
    return envelope(doc)


@router.patch("/{anchor}")
async def patch_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    body: PatchSectionRequest,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.patch_section(repo, key, anchor, body.patch)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.delete("/{anchor}")
async def remove_section(
    uid: str,
    project: str,
    slug: str,
    anchor: str,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    # Returns 200 + envelope, not 204: the mutated document is in the response body.
    key = document_key(uid, project, slug)
    rev, doc = await core.remove_section(repo, key, anchor)
    response.headers["ETag"] = rev
    return envelope(doc)
