"""Task routes — thin over core.py.

add_task with no --at is a retry-safe append (no client rev needed). add_task with
--at N is a positional insert that goes through the same retry-safe
read_modify_write path (no --rev), but is best-effort under concurrent inserts: a
CAS retry re-inserts at the same absolute index, so under a concurrent insert the
final ordinal may differ from what the caller observed. This is the deliberate
phase-3/phase-5 --rev-gating decision, not a bug.

Index-addressed ops (toggle/edit/remove) require the client's rev via If-Match: a
concurrent insert/remove would shift indices, so the caller must target the rev it
last saw.
"""

from fastapi import APIRouter, Response

from claudeplans_contracts import (
    AddTaskRequest,
    EditTaskRequest,
    ToggleTaskRequest,
    document_key,
)

from .. import core
from ..events import Event
from .deps import CurrentUserDep, FeedDep, IfMatchDep, RepoDep
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
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.add_task(
        repo, key, phase_slug, body.text, body.at, body.checked, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"phases.{phase_slug}")


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
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.toggle_task(
        repo, key, phase_slug, task_index, body.checked, expected_rev, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"phases.{phase_slug}")


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
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    key = document_key(uid, project, slug)
    rev, doc = await core.edit_task(
        repo, key, phase_slug, task_index, body.text, expected_rev, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"phases.{phase_slug}")


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
    user: CurrentUserDep,
    feed: FeedDep,
) -> ResponseEnvelope:
    # Returns 200 + envelope, not 204: the mutated document is in the response body.
    key = document_key(uid, project, slug)
    rev, doc = await core.remove_task(
        repo, key, phase_slug, task_index, expected_rev, user=user
    )
    response.headers["ETag"] = rev
    feed.publish(Event(key=key, rev=rev))
    return envelope(doc, scope=f"phases.{phase_slug}")
