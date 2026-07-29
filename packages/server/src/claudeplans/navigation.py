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
from claudeplans_contracts.enums import DocStatus, DocType
from claudeplans_contracts.errors import PlanError

from . import core
from .auth.registry import UserRegistry
from .lineage import ChildRef, Lineage, ParentRef, build_lineage
from .projects import ProjectRegistry
from .storage.repository import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProjectTree:
    """One project's documents, grouped into a lineage tree for the sidebar.

    `lineage` covers the active (non-archived) docs; `archived` is the same fold
    over the docs with `DocStatus.archived`.
    """

    project: str
    name: str
    lineage: Lineage
    archived: Lineage
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


def _split_lineages(docs: list[Document]) -> tuple[Lineage, Lineage]:
    """Fold docs into (active, archived) lineages, partitioned by archived status."""
    active = [d for d in docs if d.status is not DocStatus.archived]
    archived = [d for d in docs if d.status is DocStatus.archived]
    return build_lineage(active), build_lineage(archived)


async def load_project_lineage(
    repo: Repository, uid: str, project: str
) -> tuple[Lineage, Lineage]:
    """Fold one user+project's documents into (active, archived) Lineages.

    Poison docs are skipped. Docs with `DocStatus.archived` are folded into the
    second (archived) lineage instead of the first.
    """
    # Trailing slash scopes to the project segment exactly: validate_key_segment
    # forbids slashes in a segment, so "uid/project/" can't match a sibling.
    prefix = f"{uid}/{project}/"
    keys = [entry.key for entry in await repo.list(prefix)]
    return _split_lineages(await _load_documents(repo, keys))


async def resolve_parent(
    repo: Repository, uid: str, project: str, doc: Document
) -> ParentRef | None:
    """Resolve a plan's lineage parent: the research doc it names as
    `primary_parent_ref`, read once via listing metadata (no body read). None
    when there is no research parent — the same unlinked case build_lineage folds
    away.
    """
    if doc.type is not DocType.plan or doc.primary_parent_ref is None:
        return None
    prefix = f"{uid}/{project}/"
    for entry in await repo.list(prefix):
        if entry.key.rsplit("/", 1)[1] != doc.primary_parent_ref:
            continue
        if entry.metadata.get("type") != "research":
            return None
        return ParentRef(
            slug=doc.primary_parent_ref,
            title=entry.metadata.get("title", ""),
        )
    return None


async def resolve_children(
    repo: Repository, uid: str, project: str, doc: Document
) -> list[ChildRef]:
    """Resolve a research doc's sub-docs: the plans whose `primary_parent_ref` is
    this doc, folded via build_lineage exactly as the sidebar and lineage page do —
    so the index never disagrees with them. Empty for a non-research doc or one with
    no sub-docs.

    Status-agnostic, mirroring resolve_parent: the fold is over every project doc, so
    an archived research doc still lists its children and an archived child still
    appears under its parent — the reciprocal of the child's upward trail, which
    resolve_parent already renders across the archived boundary. A single fold (not
    load_project_lineage's active/archived split) is what makes this cross-status:
    build_lineage can only nest a plan under a research doc when both sit in the same
    input set.

    Unlike resolve_parent — which matches the in-hand doc's own primary_parent_ref
    against listing metadata (no body read) — the nesting key lives on the other docs,
    and primary_parent_ref is not a listing-metadata field, so this reads the project
    bodies. The sidebar build reads them too; that double read is accepted at local
    single-user scale (dedup by threading one load through the view is a later change).
    """
    if doc.type is not DocType.research:
        return []
    prefix = f"{uid}/{project}/"
    keys = [entry.key for entry in await repo.list(prefix)]
    lineage = build_lineage(await _load_documents(repo, keys))
    node = next((n for n in lineage.research if n.slug == doc.slug), None)
    if node is None:
        return []
    return [ChildRef(slug=plan.slug, title=plan.title) for plan in node.plans]


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
        active, archived = _split_lineages(docs)
        trees.append(
            ProjectTree(
                project=project,
                name=names.get(project, project),
                lineage=active,
                archived=archived,
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
