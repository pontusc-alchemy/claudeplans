"""Orchestration — the single path a write flows through. Called by API routers.

Per write today: apply the delta, then re-validate the result by re-constructing
the Document (model_validate over the JSON dump) so field validators and the model
invariants run BEFORE anything is persisted — a mutation that violates an invariant
raises pydantic.ValidationError (mapped to HTTP 422) instead of being written and
poisoning the store. The validated dump is then persisted under the Repository's
compare-and-set: stable-key/absolute deltas go through a bounded server-side
read-modify-write retry so a false 409 never reaches the agent, while position-
or index-sensitive deltas carry the client's If-Match rev and surface StaleRevision
as a 409. Routers stay thin: parse, call core, return.

Authz (can_write) is enforced HERE on every write (write-own: a caller may write
only within its own namespace); reads are unrestricted (read-all). Change-event
emission is performed by the API layer — the composition point that holds both the
key and the new rev — keeping core a pure storage-orchestration layer.
"""

from collections.abc import Callable
from typing import Final

from pydantic import JsonValue

from claudeplans_contracts import (
    MAX_LINEAGE_DEPTH,
    Document,
    DocumentCreate,
    Forbidden,
    StaleRevision,
    ValidationError,
    key_for_document,
    migrate_document,
    owner_of,
)
from claudeplans_contracts.enums import DocStatus, PhaseStatus, SectionPlacement

from . import deltas
from .auth.authz import can_write
from .auth.provider import CurrentUser
from .storage.repository import CREATE, ListEntry, Repository

# A commutative/absolute delta should never surface a false 409 to the agent just
# because a concurrent write bumped the rev mid-flight; bound the re-read loop so a
# genuinely contended key still fails loud instead of spinning forever.
MAX_WRITE_RETRIES: Final = 5


def _require_write(user: CurrentUser, namespace: str) -> None:
    """Enforce write-own at the single write path. Reads are unrestricted.

    Called BEFORE any repo.get on every write path, so an unauthorized caller gets
    403 instead of (and before) a 404/409 — existence and rev never leak across
    namespaces.
    """
    if not can_write(user, namespace):
        raise Forbidden(f"user {user.uid!r} may not write in namespace {namespace!r}")


async def read_modify_write(
    repo: Repository,
    key: str,
    mutate: Callable[[Document], Document],
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    """Apply `mutate` to the stored document under CAS, retrying on StaleRevision.

    On a lost compare-and-set race the document is re-read and `mutate` re-applied,
    so commutative/absolute deltas never raise a false 409. `mutate` MUST therefore
    be safe to re-apply against a freshly re-read state — express deltas as absolute
    sets, not relative flips. StaleRevision is raised only once the retry budget is
    spent (the API maps that to HTTP 409).
    """
    _require_write(user, owner_of(key))
    for _ in range(MAX_WRITE_RETRIES):
        rev, raw = await repo.get(key)
        current = migrate_document(raw)
        updated = mutate(current)
        # Re-validate before persisting: model_copy(update=...) inside the deltas does
        # NOT re-run field validators or _check_invariants, so without this an
        # invariant-violating mutation would reach disk and poison every later read.
        dumped = updated.model_dump(mode="json")
        Document.model_validate(dumped)
        try:
            new_rev = await repo.put(key, dumped, rev)
        except StaleRevision:
            continue
        return new_rev, updated
    # Retry budget spent on a genuinely contended key: re-read so the 409 still
    # carries a usable current rev (the "retry without re-read" promise must hold
    # exactly when this fires). NotFound here means the key was deleted mid-contention
    # and propagates as a 404, which is the truthful outcome.
    current_rev, _ = await repo.get(key)
    raise StaleRevision(
        f"write to {key!r} lost {MAX_WRITE_RETRIES} CAS races",
        current_rev=current_rev,
    )


async def _write_at_rev(
    repo: Repository,
    key: str,
    expected_rev: str,
    mutate: Callable[[Document], Document],
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    """Apply `mutate` under optimistic concurrency: the caller's rev must still
    match (StaleRevision -> 409 otherwise). Re-validates the result before
    persisting so an invariant violation 422s instead of poisoning the store."""
    _require_write(user, owner_of(key))
    _, raw = await repo.get(key)
    updated = mutate(migrate_document(raw))
    dumped = updated.model_dump(mode="json")
    Document.model_validate(dumped)
    new_rev = await repo.put(key, dumped, expected_rev)
    return new_rev, updated


# --- Document lifecycle -----------------------------------------------------


async def create_document(
    repo: Repository,
    *,
    owner_id: str,
    project: str,
    doc_in: DocumentCreate,
    user: CurrentUser,
) -> tuple[str, Document]:
    """Compose a Document from `doc_in` + path identity and create it (CREATE).

    owner_id/project come from the URL path (not the wire body) and schema_version
    is server-set via the Document default. StaleRevision (the key already exists)
    propagates -> 409.
    """
    _require_write(user, owner_id)
    # create bypasses put_research_refs entirely, so without this a create naming a
    # cycle-closing parent would be admitted with no 422.
    if doc_in.research_refs or doc_in.primary_parent_ref:
        entries = list(await repo.list(f"{owner_id}/{project}/"))
        _check_refs_exist(entries, doc_in.research_refs)
        # A new doc has no descendants, so its chain to root is the whole story.
        _check_parent_is_legal(
            entries, doc_in.slug, doc_in.primary_parent_ref, with_subtree=False
        )
    doc = Document(
        type=doc_in.type,
        status=doc_in.status,
        project=project,
        slug=doc_in.slug,
        title=doc_in.title,
        owner_id=owner_id,
        date=doc_in.date,
        description=doc_in.description,
        frontmatter=doc_in.frontmatter,
        research_refs=doc_in.research_refs,
        primary_parent_ref=doc_in.primary_parent_ref,
        sections=doc_in.sections,
        phases=doc_in.phases,
    )
    key = key_for_document(doc)
    new_rev = await repo.put(key, doc.model_dump(mode="json"), CREATE)
    return new_rev, doc


async def get_document(repo: Repository, key: str) -> tuple[str, Document]:
    """Read and migrate the document at `key`. NotFound propagates -> 404."""
    rev, raw = await repo.get(key)
    return rev, migrate_document(raw)


async def delete_document(
    repo: Repository, key: str, expected_rev: str, *, user: CurrentUser
) -> None:
    """Delete `key` under the client's rev. StaleRevision -> 409, NotFound -> 404.

    Destructive, so it requires the client's rev rather than a server-side retry: a
    silent re-delete after a concurrent change could remove the wrong state.
    """
    _require_write(user, owner_of(key))
    await repo.delete(key, expected_rev)


# --- Stable-key deltas: read-modify-write (no client rev) -------------------
#
# These deltas address by stable key (document/phase slug, section anchor) and set
# absolute values, so re-applying after a concurrent write is safe. read_modify_write
# hides false conflicts by re-reading and re-applying, so the agent never sees a 409
# it would only have to blindly retry.


async def set_document_status(
    repo: Repository, key: str, status: DocStatus, *, user: CurrentUser
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.set_document_status(doc, status), user=user
    )


async def add_phase(
    repo: Repository,
    key: str,
    slug: str,
    name: str,
    status: PhaseStatus,
    intro: str = "",
    exit_criteria: str = "",
    notes: str = "",
    at: int | None = None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.add_phase(
            doc, slug, name, status, intro, exit_criteria, notes, at
        ),
        user=user,
    )


async def set_phase(
    repo: Repository,
    key: str,
    slug: str,
    name: str | None,
    intro: str | None = None,
    exit_criteria: str | None = None,
    notes: str | None = None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.set_phase(doc, slug, name, intro, exit_criteria, notes),
        user=user,
    )


async def set_phase_status(
    repo: Repository, key: str, slug: str, status: PhaseStatus, *, user: CurrentUser
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.set_phase_status(doc, slug, status), user=user
    )


async def remove_phase(
    repo: Repository, key: str, slug: str, *, user: CurrentUser
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.remove_phase(doc, slug), user=user
    )


async def add_task(
    repo: Repository,
    key: str,
    phase_slug: str,
    text: str,
    at: int | None,
    checked: bool = False,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.add_task(doc, phase_slug, text, at, checked),
        user=user,
    )


async def add_section(
    repo: Repository,
    key: str,
    anchor: str,
    heading: str,
    body: str,
    level: int,
    placement: SectionPlacement,
    at: int | None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.add_section(
            doc, anchor, heading, body, level, placement, at
        ),
        user=user,
    )


async def set_section(
    repo: Repository,
    key: str,
    anchor: str,
    heading: str | None,
    body: str | None,
    level: int | None,
    placement: SectionPlacement | None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.set_section(doc, anchor, heading, body, level, placement),
        user=user,
    )


async def patch_section(
    repo: Repository,
    key: str,
    anchor: str,
    patch: dict[str, JsonValue],
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.patch_section(doc, anchor, patch), user=user
    )


async def remove_section(
    repo: Repository, key: str, anchor: str, *, user: CurrentUser
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.remove_section(doc, anchor), user=user
    )


async def set_document_meta(
    repo: Repository,
    key: str,
    *,
    title: str | None,
    description: str | None,
    date: str | None,
    frontmatter: dict[str, JsonValue] | None,
    clear_description: bool = False,
    clear_date: bool = False,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.set_document_meta(
            doc,
            title=title,
            description=description,
            date=date,
            frontmatter=frontmatter,
            clear_description=clear_description,
            clear_date=clear_date,
        ),
        user=user,
    )


def _slugs_and_parents(entries: list[ListEntry]) -> dict[str, str]:
    """slug -> parent slug ("" for a root) for every doc in one project listing."""
    return {
        e.key.rsplit("/", 1)[1]: e.metadata.get("primary_parent_ref", "")
        for e in entries
    }


def _check_refs_exist(entries: list[ListEntry], refs: list[str]) -> None:
    """Every ref must name a doc in the same project, of ANY type.

    The research-type constraint is gone — any doc may parent any doc — but the
    existence check is deliberately kept: without it, linking a ref that does not
    exist would silently persist a dangling backlink.
    """
    known = _slugs_and_parents(entries)
    unresolved = [r for r in refs if r not in known]
    if unresolved:
        raise ValidationError(
            f"research ref(s) do not resolve to a doc in project: "
            f"{', '.join(unresolved)}"
        )


def _subtree_height(parents: dict[str, str], slug: str) -> int:
    """Levels beneath `slug`, counting itself as 1."""
    children: dict[str, list[str]] = {}
    for child, parent in parents.items():
        if parent:
            children.setdefault(parent, []).append(child)

    def height(node: str, depth: int) -> int:
        if depth > MAX_LINEAGE_DEPTH:
            return depth
        return max(
            (height(k, depth + 1) for k in children.get(node, [])), default=depth
        )

    return height(slug, 1)


def _check_parent_is_legal(
    entries: list[ListEntry],
    slug: str,
    parent: str | None,
    *,
    with_subtree: bool,
) -> None:
    """Reject a parent that would close a cycle or push the tree past the cap —
    acyclicity spans the whole project, so it cannot live on the model."""
    if parent is None:
        return
    if parent == slug:
        raise ValidationError("primary_parent_ref must not be the document itself")
    parents = _slugs_and_parents(entries)

    chain = 1
    seen = {slug}
    cursor: str | None = parent
    while cursor:
        if cursor in seen:
            raise ValidationError(
                f"primary_parent_ref {parent!r} would create a cycle through {cursor!r}"
            )
        seen.add(cursor)
        chain += 1
        cursor = parents.get(cursor) or None

    # Moving a doc carries its subtree, so a reparent measures both directions;
    # checking only the upward chain lets descendants land past the cap unseen.
    depth = chain + (_subtree_height(parents, slug) - 1 if with_subtree else 0)
    if depth > MAX_LINEAGE_DEPTH:
        raise ValidationError(
            f"primary_parent_ref {parent!r} would nest {slug!r} to depth {depth}, "
            f"past the limit of {MAX_LINEAGE_DEPTH}"
        )


async def put_research_refs(
    repo: Repository,
    key: str,
    research_refs: list[str],
    primary: str | None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    # Authz first: a cross-namespace caller must get 403 before any repo access.
    _require_write(user, owner_of(key))
    # key = "{owner}/{project}/{slug}"; project prefix = "{owner}/{project}/".
    project_prefix, slug = key.rsplit("/", 1)
    entries = list(await repo.list(project_prefix + "/"))
    _check_refs_exist(entries, research_refs)
    # Reparenting carries the whole subtree, so the depth check spans both ways.
    _check_parent_is_legal(entries, slug, primary, with_subtree=True)
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.put_research_refs(doc, research_refs, primary),
        user=user,
    )


# --- Position- / index-sensitive deltas: require the client's rev -----------
#
# move_phase reorders, and the task ops address a task by list index, so re-applying
# after a concurrent structural change (an insert/remove/reorder shifting positions)
# would silently corrupt the wrong target. They take the client's expected_rev and
# let StaleRevision surface as a 409 rather than retrying — the agent must re-read
# and re-target.


async def move_phase(
    repo: Repository,
    key: str,
    slug: str,
    to_index: int,
    expected_rev: str,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await _write_at_rev(
        repo,
        key,
        expected_rev,
        lambda doc: deltas.move_phase(doc, slug, to_index),
        user=user,
    )


async def move_section(
    repo: Repository,
    key: str,
    anchor: str,
    to_index: int,
    expected_rev: str,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await _write_at_rev(
        repo,
        key,
        expected_rev,
        lambda doc: deltas.move_section(doc, anchor, to_index),
        user=user,
    )


async def toggle_task(
    repo: Repository,
    key: str,
    phase_slug: str,
    task_index: int,
    checked: bool,
    expected_rev: str,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await _write_at_rev(
        repo,
        key,
        expected_rev,
        lambda doc: deltas.toggle_task(doc, phase_slug, task_index, checked),
        user=user,
    )


async def set_tasks_checked(
    repo: Repository,
    key: str,
    phase_slug: str,
    indices: list[int] | None,
    checked: bool,
    expected_rev: str | None,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    def mutate(doc: Document) -> Document:
        return deltas.set_tasks_checked(doc, phase_slug, indices, checked)

    if indices is None:
        return await read_modify_write(repo, key, mutate, user=user)
    if expected_rev is None:
        raise ValidationError("rev required when targeting explicit task indices")
    return await _write_at_rev(repo, key, expected_rev, mutate, user=user)


async def complete_phase(
    repo: Repository, key: str, phase_slug: str, *, user: CurrentUser
) -> tuple[str, Document]:
    return await read_modify_write(
        repo, key, lambda doc: deltas.complete_phase(doc, phase_slug), user=user
    )


async def edit_task(
    repo: Repository,
    key: str,
    phase_slug: str,
    task_index: int,
    text: str,
    expected_rev: str,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await _write_at_rev(
        repo,
        key,
        expected_rev,
        lambda doc: deltas.edit_task(doc, phase_slug, task_index, text),
        user=user,
    )


async def remove_task(
    repo: Repository,
    key: str,
    phase_slug: str,
    task_index: int,
    expected_rev: str,
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await _write_at_rev(
        repo,
        key,
        expected_rev,
        lambda doc: deltas.remove_task(doc, phase_slug, task_index),
        user=user,
    )
