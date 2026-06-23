"""Task routes — thin over core.py.

Append (add_task) is retry-safe and needs no client rev. Index-addressed ops
(toggle/edit/remove) require the client's rev via If-Match: a concurrent
insert/remove would shift indices, so the caller must target the rev it last saw.
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    AddTaskRequest,
    EditTaskRequest,
    ToggleTaskRequest,
    document_key,
)

from .. import core
from .deps import IfMatchDep, RepoDep
from .envelope import ResponseEnvelope, envelope

router = APIRouter(
    prefix="/v1/users/{uid}/projects/{project}/docs/{slug}/phases/{phase_slug}/tasks",
    tags=["tasks"],
)


@router.post("")
async def add_task(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    body: AddTaskRequest,
    response: Response,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.add_task(repo, key, phase_slug, body.text)
    response.headers["ETag"] = rev
    return envelope(doc)


@router.put("/{task_index}/toggle")
async def toggle_task(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: int,
    body: ToggleTaskRequest,
    response: Response,
    expected_rev: IfMatchDep,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.toggle_task(
        repo, key, phase_slug, task_index, body.checked, expected_rev
    )
    response.headers["ETag"] = rev
    return envelope(doc)


@router.put("/{task_index}")
async def edit_task(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: int,
    body: EditTaskRequest,
    response: Response,
    expected_rev: IfMatchDep,
    repo: RepoDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.edit_task(
        repo, key, phase_slug, task_index, body.text, expected_rev
    )
    response.headers["ETag"] = rev
    return envelope(doc)


@router.delete("/{task_index}")
async def remove_task(
    uid: str,
    project: str,
    slug: str,
    phase_slug: str,
    task_index: int,
    response: Response,
    expected_rev: IfMatchDep,
    repo: RepoDep,
) -> ResponseEnvelope:
    # Returns 200 + envelope, not 204: the mutated document is in the response body.
    key = document_key(uid, project, slug)
    rev, doc = await core.remove_task(repo, key, phase_slug, task_index, expected_rev)
    response.headers["ETag"] = rev
    return envelope(doc)
