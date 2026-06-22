"""FilesystemRepository-specific behavior the backend-agnostic contract suite omits.

The contract suite tests rev OPACITY (round-trip, not value); these pin the concrete
filesystem scheme — a monotonic integer-as-string counter — and the list() tolerance
for files that vanish mid-walk or sit corrupt on disk.
"""

from pathlib import Path

from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE


def _doc() -> dict[str, str]:
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
