"""Sidebar navigation data: per-user project trees and the user-switcher list.

Pure-ish async builders over the repository — no FastAPI, no templates. The HTML
layer (api/view.py) calls these and threads the result into the sidebar context.
Each project's documents are folded into a Lineage (build_lineage) exactly as the
per-project lineage page does, so the sidebar mirrors that view's structure.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from claudeplans_contracts import Document
from claudeplans_contracts.errors import PlanError

from . import core
from .auth.registry import UserRegistry
from .lineage import Lineage, build_lineage
from .projects import ProjectRegistry
from .storage.repository import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectTree:
    """One project's documents, grouped into a lineage tree for the sidebar."""

    project: str
    name: str
    lineage: Lineage
    doc_count: int


@dataclass(frozen=True, slots=True)
class UserEntry:
    """One option in the user switcher."""

    uid: str
    name: str
    current: bool


async def _load_documents(repo: Repository, keys: Iterable[str]) -> list[Document]:
    """Load each key via the strict parse path, skipping any poison doc.

    repo.list is lenient but get_document is strict: a doc can be deleted in a
    race, carry a corrupt envelope, or be a legacy body the current model rejects
    (e.g. a `@end` section anchor). Skip the poison doc rather than error the whole
    view — every page (sidebar + lineage) loads through here.
    """
    docs: list[Document] = []
    for key in keys:
        try:
            _, doc = await core.get_document(repo, key)
        except (PlanError, ValidationError) as exc:
            logger.warning("skipping unloadable document %s: %s", key, exc)
            continue
        docs.append(doc)
    return docs


async def load_project_lineage(repo: Repository, uid: str, project: str) -> Lineage:
    """Fold one user+project's documents into a Lineage, poison docs skipped."""
    # Trailing slash scopes to the project segment exactly: validate_key_segment
    # forbids slashes in a segment, so "uid/project/" can't match a sibling.
    prefix = f"{uid}/{project}/"
    keys = [entry.key for entry in await repo.list(prefix)]
    return build_lineage(await _load_documents(repo, keys))


async def build_user_tree(
    repo: Repository, uid: str, project_registry: ProjectRegistry | None = None
) -> list[ProjectTree]:
    """Group `uid`'s documents by project and fold each into a Lineage.

    Mirrors api.view.project_lineage's load pattern (list -> get each -> build_lineage)
    but across every project the user owns, returned sorted by project name.
    `project_registry` supplies display names; falls back to slug when None or unset.
    """
    by_project: dict[str, list[str]] = {}
    for entry in await repo.list(f"{uid}/"):
        parts = entry.key.split("/")
        if len(parts) < 2:
            continue
        by_project.setdefault(parts[1], []).append(entry.key)

    names: dict[str, str] = (
        project_registry.names_for(uid) if project_registry is not None else {}
    )

    trees: list[ProjectTree] = []
    for project in sorted(by_project):
        docs = await _load_documents(repo, by_project[project])
        trees.append(
            ProjectTree(
                project=project,
                name=names.get(project, project),
                lineage=build_lineage(docs),
                doc_count=len(docs),
            )
        )
    return trees


async def list_users(
    repo: Repository, registry: UserRegistry, current_uid: str
) -> list[UserEntry]:
    """The user-switcher options: everyone who actually has plans.

    Union of the top-level storage namespaces (uids that own documents), any
    registered users, and `current_uid` (the dev user is implicit and never minted
    into the registry). Display the registry name when known, else the raw uid.
    Sorted by display name; the current user is flagged.
    """
    storage_uids: set[str] = set()
    for entry in await repo.list(""):
        parts = entry.key.split("/")
        if len(parts) >= 2 and parts[0]:
            storage_uids.add(parts[0])

    names = {rec.uid: rec.name for rec in registry.records()}
    uids = storage_uids | set(names) | {current_uid}

    entries = [
        UserEntry(uid=uid, name=names.get(uid, uid), current=uid == current_uid)
        for uid in uids
    ]
    return sorted(entries, key=lambda e: (e.name, e.uid))
