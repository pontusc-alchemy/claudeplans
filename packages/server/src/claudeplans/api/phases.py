"""Phase routes — thin over core.py.

Phase ops address by stable slug and set absolute values, so they are re-apply-safe
and need no client rev (core hides false conflicts via read-modify-write).
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    AddPhaseRequest,
    MovePhaseRequest,
    PhaseStatusRequest,
    document_key,
)

from .. import core
from .deps import IfMatchDep, RepoDep
from .envelope import ResponseEnvelope, envelope

router = APIRouter(
    prefix="/v1/users/{uid}/projects/{project}/docs/{slug}/phases",
    tags=["phases"],
)


@router.post("")
async def add_phase(
    uid: str,
    project: str,
    slug: str,
    body: AddPhaseRequest,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.add_phase(repo, key, body.slug, body.name, body.status)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.put("/{phase_slug}/status")
async def set_phase_status(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    body: PhaseStatusRequest,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.set_phase_status(repo, key, phase_slug, body.status)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.post("/{phase_slug}/move")
async def move_phase(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    body: MovePhaseRequest,
    response: Response,
    expected_rev: IfMatchDep,
    repo: RepoDep,
) -> ResponseEnvelope:
    # Reorders the phase list, so it carries the client's rev (missing -> 428,
    # stale -> 409), consistent with the index-addressed task ops.
    key = document_key(uid, project, slug)
    rev, doc = await core.move_phase(repo, key, phase_slug, body.to_index, expected_rev)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.delete("/{phase_slug}")
async def remove_phase(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.remove_phase(repo, key, phase_slug)
    response.headers["ETag"] = rev
    return envelope(doc)
