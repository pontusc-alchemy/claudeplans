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
    document_key,
)

from .. import core
from .deps import CurrentUserDep, IfMatchDep, RepoDep
from .envelope import ResponseEnvelope, envelope

router = APIRouter(prefix="/v1/users/{uid}/projects/{project}/docs", tags=["documents"])


@router.post("", status_code=201)
async def create(
    uid: str,
    project: str,
    body: DocumentCreate,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
) -> ResponseEnvelope:
    rev, doc = await core.create_document(
        repo, owner_id=uid, project=project, doc_in=body, user=user
    )
    response.headers["ETag"] = rev
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
) -> Response:
    key = document_key(uid, project, slug)
    await core.delete_document(repo, key, expected_rev, user=user)
    return Response(status_code=204)


@router.put("/{slug}/status")
async def set_status(
    uid: str,
    project: str,
    slug: str,
    body: DocStatusRequest,
    response: Response,
    repo: RepoDep,
    user: CurrentUserDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_document_status(repo, key, body.status, user=user)
    response.headers["ETag"] = rev
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
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.put_research_refs(
        repo, key, body.research_refs, body.primary_research_ref, user=user
    )
    response.headers["ETag"] = rev
    return envelope(doc)
