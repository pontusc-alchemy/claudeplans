"""Search route — title + section/phase heading search over the in-memory index.

Read-only and open (reads are unrestricted in the auth model, like the lineage and
view pages). Scoped to one user+project via a key prefix, matching the lineage route:
the trailing slash pins the scope to the exact `{uid}/{project}/` segment so a sibling
project can't leak. The index is built/kept-fresh in the lifespan (see main.py); this
route is a pure synchronous read over its current snapshot.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from claudeplans_contracts import SearchResults, validate_key_segment

from ..projects import ProjectRegistry
from .deps import ProjectRegistryDep, SearchIndexDep

router = APIRouter(tags=["search"])


def _with_names(
    results: SearchResults, registry: ProjectRegistry, uid: str
) -> SearchResults:
    """Stamp each hit with its project's display name (registry → slug fallback)."""
    hits = [
        h.model_copy(update={"project_name": registry.get(uid, h.project) or h.project})
        for h in results.hits
    ]
    return SearchResults(query=results.query, hits=hits)


@router.get("/v1/users/{uid}/projects/{project}/search")
async def search_project(
    uid: str,
    project: str,
    index: SearchIndexDep,
    project_registry: ProjectRegistryDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search text")],
) -> SearchResults:
    """Return title/heading/phase-name hits within one user+project."""
    # Validate the path segments the same way the document routes do (via
    # validate_key_segment), so a malformed uid/project gets a clean 422 instead of
    # silently scoping to an impossible prefix and returning no hits.
    try:
        validate_key_segment(uid)
        validate_key_segment(project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _with_names(
        index.query(q, prefix=f"{uid}/{project}/"), project_registry, uid
    )


@router.get("/v1/users/{uid}/search")
async def search_user(
    uid: str,
    index: SearchIndexDep,
    project_registry: ProjectRegistryDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="Search text")],
) -> SearchResults:
    """Hits across all of `uid`'s projects, each tagged with its project name."""
    try:
        validate_key_segment(uid)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _with_names(index.query(q, prefix=f"{uid}/"), project_registry, uid)
