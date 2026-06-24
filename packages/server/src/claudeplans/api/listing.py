"""Listing routes — enumerate projects and documents for a user.

Read-only and open (no auth dep), mirroring the search router pattern. Results
are built from metadata stored alongside each document in the repository, so
no document body is fetched during a list call.
"""

from fastapi import APIRouter, HTTPException

from claudeplans_contracts import (
    DocList,
    DocListEntry,
    DocStatus,
    DocType,
    ProjectEntry,
    ProjectList,
    validate_key_segment,
)

from ..storage.repository import ListEntry
from .deps import RepoDep

router = APIRouter(tags=["listing"])


def _doc_row(entry: ListEntry) -> DocListEntry | None:
    """Return a DocListEntry for a valid entry, or None to skip it.

    Skips entries whose key is not exactly uid/project/slug (3 segments), or
    whose type/status metadata fails enum coercion — so a corrupt on-disk
    envelope is silently omitted from both doc list and project counts.
    """
    parts = entry.key.split("/")
    if len(parts) != 3:
        return None
    slug = parts[2]
    try:
        title = entry.metadata["title"]
        doc_type = DocType(entry.metadata["type"])
        status = DocStatus(entry.metadata["status"])
    except KeyError, ValueError:
        # Missing or invalid enum value: skip rather than 500.
        return None
    return DocListEntry(slug=slug, title=title, type=doc_type, status=status)


@router.get("/v1/users/{uid}/projects")
async def list_projects(uid: str, repo: RepoDep) -> ProjectList:
    """Return every project owned by `uid` with its document count, sorted by name."""
    try:
        validate_key_segment(uid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    entries = list(await repo.list(f"{uid}/"))
    counts: dict[str, int] = {}
    for entry in entries:
        row = _doc_row(entry)
        if row is None:
            continue
        project = entry.key.split("/")[1]
        counts[project] = counts.get(project, 0) + 1

    items = [ProjectEntry(project=p, docs=n) for p, n in sorted(counts.items())]
    return ProjectList(items=items)


@router.get("/v1/users/{uid}/projects/{project}/docs")
async def list_docs(uid: str, project: str, repo: RepoDep) -> DocList:
    """Return every document in `uid/project`, sorted by slug."""
    try:
        validate_key_segment(uid)
        validate_key_segment(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    entries = list(await repo.list(f"{uid}/{project}/"))
    items: list[DocListEntry] = []
    for entry in entries:
        row = _doc_row(entry)
        if row is None:
            continue
        items.append(row)

    items.sort(key=lambda e: e.slug)
    return DocList(project=project, items=items)
