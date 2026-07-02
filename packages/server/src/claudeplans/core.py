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
from .storage.repository import CREATE, Repository

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
        primary_research_ref=doc_in.primary_research_ref,
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
    *,
    user: CurrentUser,
) -> tuple[str, Document]:
    return await read_modify_write(
        repo,
        key,
        lambda doc: deltas.add_phase(
            doc, slug, name, status, intro, exit_criteria, notes
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
        ),
        user=user,
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
    # Validate that every ref resolves to a research-type doc in the same project.
    # key = "{owner}/{project}/{slug}"; project prefix = "{owner}/{project}/".
    prefix = key.rsplit("/", 1)[0] + "/"
    entries = await repo.list(prefix)
    research_slugs = {
        e.key.rsplit("/", 1)[1] for e in entries if e.metadata.get("type") == "research"
    }
    unresolved = [r for r in research_refs if r not in research_slugs]
    if unresolved:
        raise ValidationError(
            f"research ref(s) do not resolve to a research doc in project: "
            f"{', '.join(unresolved)}"
        )
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
