"""Listing routes — enumerate projects and documents for a user.

Read-only listing routes are open (no auth dep), mirroring the search router
pattern. The project name write route uses the owner-auth dependency exactly as
the document write routes do.
"""

from fastapi import APIRouter, HTTPException

from claudeplans_contracts import (
    DocList,
    DocListEntry,
    DocStatus,
    DocType,
    ProjectEntry,
    ProjectList,
    ProjectName,
    validate_key_segment,
)

from ..auth.authz import can_write
from ..storage.repository import ListEntry
from .deps import CurrentUserDep, ProjectRegistryDep, RepoDep

router = APIRouter(tags=["listing"])


def _doc_row(entry: ListEntry) -> DocListEntry | None:
    """Return a DocListEntry for a valid entry, or None to skip it.

    Skips entries whose key is not exactly uid/project/slug (3 segments), or
    whose type/status metadata fails enum coercion — so a corrupt on-disk
    envelope is silently omitted from both doc list and project counts.

    rev/updated_at/primary_research_ref ride along from data the listing already
    holds, so they cost no extra read. They are read with `.get(...) or None`, never
    subscripted: an absent or empty value must degrade to null, not skip the row.
    """
    parts = entry.key.split("/")
    if len(parts) != 3:
        return None
    slug = parts[2]
    try:
        title = entry.metadata["title"]
        doc_type = DocType(entry.metadata["type"])
        status = DocStatus(entry.metadata["status"])
    except KeyError, ValueError:  # unparenthesized multi-except: PEP 758 (3.14)
        # Missing or invalid enum value: skip rather than 500.
        return None
    return DocListEntry(
        slug=slug,
        title=title,
        type=doc_type,
        status=status,
        rev=entry.rev or None,
        updated_at=entry.metadata.get("updated_at") or None,
        primary_research_ref=entry.metadata.get("primary_research_ref") or None,
    )


@router.get("/v1/users/{uid}/projects")
async def list_projects(
    uid: str, repo: RepoDep, project_registry: ProjectRegistryDep
) -> ProjectList:
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

    names = project_registry.names_for(uid)
    items = [
        ProjectEntry(project=p, docs=n, name=names.get(p))
        for p, n in sorted(counts.items())
    ]
    return ProjectList(items=items)


@router.put("/v1/users/{uid}/projects/{project}/name")
async def set_project_name(
    uid: str,
    project: str,
    body: ProjectName,
    user: CurrentUserDep,
    project_registry: ProjectRegistryDep,
) -> dict[str, str]:
    """Set the display name for a project (registry metadata, not a versioned doc)."""
    if not can_write(user, uid):
        raise HTTPException(status_code=403, detail="forbidden")
    try:
        validate_key_segment(uid)
        validate_key_segment(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project_registry.set(uid, project, body.name)
    return {"project": project, "name": body.name}


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
