"""FilesystemRepository-specific behavior the backend-agnostic contract suite omits.

The contract suite tests rev OPACITY (round-trip, not value); these pin the concrete
filesystem scheme — a monotonic integer-as-string counter — and the list() tolerance
for files that vanish mid-walk or sit corrupt on disk.
"""

from pathlib import Path

from pydantic import JsonValue

from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE


def _doc() -> dict[str, JsonValue]:
    return {
        "type": "plan",
        "project": "demo",
        "slug": "p1",
        "title": "Plan One",
        "owner_id": "u1",
    }


async def test_rev_is_monotonic_integer_counter(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    key = "u1/demo/plan/p1"
    assert await repo.put(key, _doc(), CREATE) == "1"
    assert await repo.put(key, _doc(), "1") == "2"
    assert await repo.put(key, _doc(), "2") == "3"


async def test_walk_skips_file_deleted_mid_listing(tmp_path: Path) -> None:
    # rglob yields lazily, so a file can be unlinked between yield and read. Simulate
    # the gap directly: an empty file vanishes, leaving the valid doc as the only entry.
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await repo.put("u1/demo/plan/p1", _doc(), CREATE)

    ghost = root / "u1" / "demo" / "plan" / "ghost.json"
    ghost.write_text("{}")
    ghost.unlink()

    entries = list(await repo.list(""))
    assert {e.key for e in entries} == {"u1/demo/plan/p1"}


async def test_walk_skips_corrupt_file(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await repo.put("u1/demo/plan/p1", _doc(), CREATE)

    # A hand-edited / truncated envelope must not 500 the whole listing.
    (root / "u1" / "demo" / "plan" / "broken.json").write_text("{ not json")

    entries = list(await repo.list(""))
    assert {e.key for e in entries} == {"u1/demo/plan/p1"}


async def test_walk_skips_non_object_json(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await repo.put("u1/demo/plan/p1", _doc(), CREATE)

    # Valid JSON but not an object must not 500 the whole listing either.
    (root / "u1" / "demo" / "plan" / "bad.json").write_text("[1, 2, 3]")

    entries = list(await repo.list(""))
    assert {e.key for e in entries} == {"u1/demo/plan/p1"}


def _doc_with(**extra: JsonValue) -> dict[str, JsonValue]:
    return _doc() | extra


async def _parent_meta(tmp_path: Path, doc: dict[str, JsonValue]) -> str:
    repo = FilesystemRepository(tmp_path / "data")
    await repo.put("u1/demo/p1", doc, CREATE)
    entry = next(iter(await repo.list("u1/")))
    return entry.metadata["primary_parent_ref"]


async def test_listing_projects_the_parent_ref(tmp_path: Path) -> None:
    doc = _doc_with(research_refs=["r1"], primary_parent_ref="r1")
    assert await _parent_meta(tmp_path, doc) == "r1"


async def test_listing_projects_a_v1_parent_ref_under_its_old_name(
    tmp_path: Path,
) -> None:
    """A stored doc not rewritten since the schema bump must still root correctly.

    list() projects straight off the envelope without running migrate(), so reading
    only the v2 key would silently re-root every un-migrated document.
    """
    doc = _doc_with(schema_version=1, research_refs=["r1"], primary_research_ref="r1")
    assert await _parent_meta(tmp_path, doc) == "r1"


async def test_listing_reports_a_root_as_empty_string(tmp_path: Path) -> None:
    assert await _parent_meta(tmp_path, _doc()) == ""


async def test_listing_ignores_a_non_string_parent_ref(tmp_path: Path) -> None:
    """A hand-edited body must degrade to "root", not crash the whole index."""
    assert await _parent_meta(tmp_path, _doc_with(primary_parent_ref=42)) == ""
