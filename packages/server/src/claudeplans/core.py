"""Orchestration — the single path a write flows through. Called by API routers.

Per write: validate (claudeplans_contracts model) -> authz (can_write) -> persist
(Repository CAS, with a bounded server-side read-modify-write retry for
commutative deltas so false conflicts never reach the agent) -> emit a change
Event -> invalidate the render cache. Routers stay thin: parse, call core,
return. The functions land in the storage and API phases; this module marks the
seam.
"""

from collections.abc import Callable
from typing import Final

from claudeplans_contracts import Document, StaleRevision, migrate_document

from .storage.repository import Repository

# A commutative/absolute delta should never surface a false 409 to the agent just
# because a concurrent write bumped the rev mid-flight; bound the re-read loop so a
# genuinely contended key still fails loud instead of spinning forever.
MAX_WRITE_RETRIES: Final = 5


async def read_modify_write(
    repo: Repository,
    key: str,
    mutate: Callable[[Document], Document],
) -> tuple[str, Document]:
    """Apply `mutate` to the stored document under CAS, retrying on StaleRevision.

    On a lost compare-and-set race the document is re-read and `mutate` re-applied,
    so commutative/absolute deltas never raise a false 409. `mutate` MUST therefore
    be safe to re-apply against a freshly re-read state — express deltas as absolute
    sets, not relative flips. StaleRevision is raised only once the retry budget is
    spent (the API maps that to HTTP 409).
    """
    for _ in range(MAX_WRITE_RETRIES):
        rev, raw = await repo.get(key)
        current = migrate_document(raw)
        updated = mutate(current)
        try:
            new_rev = await repo.put(key, updated.model_dump(mode="json"), rev)
        except StaleRevision:
            continue
        return new_rev, updated
    raise StaleRevision(f"write to {key!r} lost {MAX_WRITE_RETRIES} CAS races")
