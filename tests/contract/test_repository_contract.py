"""The Repository contract suite, parametrized over an adapter factory.

Parametrizing the `repo` fixture means a future GCS adapter inherits this whole
suite unchanged: add "gcs" to the fixture params and every test below runs against
it with no test-body changes.
"""

from pathlib import Path
from typing import Any

import pytest

from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE, ListEntry, Repository
from claudeplans_contracts import NotFound, StaleRevision


@pytest.fixture(params=["filesystem"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> Repository:
    # Adding "gcs" here later runs the whole suite against it with no body changes.
    if request.param == "filesystem":
        return FilesystemRepository(tmp_path / "data")
    raise ValueError(f"unknown repository backend {request.param!r}")


def _doc(slug: str = "p1") -> dict[str, Any]:
    return {
        "type": "plan",
        "project": "demo",
        "slug": slug,
        "title": "Plan One",
        "owner_id": "u1",
    }


async def _create(repo: Repository, key: str, doc: dict[str, Any]) -> str:
    return await repo.put(key, doc, CREATE)


async def test_create_then_get_round_trips(repo: Repository) -> None:
    rev1 = await _create(repo, "u1/demo/plan/p1", _doc())
    got_rev, body = await repo.get("u1/demo/plan/p1")
    # The rev put returned round-trips; its concrete form is backend-specific.
    assert got_rev == rev1
    assert body == _doc()


async def test_create_when_key_exists_is_stale(repo: Repository) -> None:
    await _create(repo, "u1/demo/plan/p1", _doc())
    with pytest.raises(StaleRevision):
        await _create(repo, "u1/demo/plan/p1", _doc())


async def test_get_missing_raises_not_found(repo: Repository) -> None:
    with pytest.raises(NotFound):
        await repo.get("u1/demo/plan/missing")


async def test_update_with_correct_rev_persists(repo: Repository) -> None:
    rev1 = await _create(repo, "u1/demo/plan/p1", _doc())
    updated = _doc() | {"title": "Renamed"}
    rev2 = await repo.put("u1/demo/plan/p1", updated, rev1)
    # A write must mint a fresh rev so the next CAS sees a moved target.
    assert rev2 != rev1
    got_rev, body = await repo.get("u1/demo/plan/p1")
    assert got_rev == rev2
    assert body["title"] == "Renamed"


async def test_update_with_stale_rev_raises(repo: Repository) -> None:
    await _create(repo, "u1/demo/plan/p1", _doc())
    with pytest.raises(StaleRevision):
        await repo.put("u1/demo/plan/p1", _doc(), "does-not-match")


async def test_delete_with_correct_rev_then_get_missing(repo: Repository) -> None:
    rev1 = await _create(repo, "u1/demo/plan/p1", _doc())
    await repo.delete("u1/demo/plan/p1", rev1)
    with pytest.raises(NotFound):
        await repo.get("u1/demo/plan/p1")


async def test_delete_with_wrong_rev_raises_stale(repo: Repository) -> None:
    await _create(repo, "u1/demo/plan/p1", _doc())
    with pytest.raises(StaleRevision):
        await repo.delete("u1/demo/plan/p1", "does-not-match")


async def test_delete_missing_raises_not_found(repo: Repository) -> None:
    with pytest.raises(NotFound):
        await repo.delete("u1/demo/plan/missing", "does-not-match")


async def test_list_scopes_to_prefix_and_carries_metadata(repo: Repository) -> None:
    await _create(repo, "u1/demo/plan/p1", _doc("p1"))
    await _create(repo, "u1/demo/plan/p2", _doc("p2"))
    await _create(repo, "u2/other/plan/q1", _doc("q1"))
    # A sibling key whose first segment shares the "u1" string prefix but not the
    # slash-terminated boundary — list("u1/") must NOT return it.
    await _create(repo, "u11/demo/plan/r1", _doc("r1"))

    entries = list(await repo.list("u1/"))
    keys = {e.key for e in entries}
    assert keys == {"u1/demo/plan/p1", "u1/demo/plan/p2"}
    for entry in entries:
        assert isinstance(entry, ListEntry)
        # Every backend must populate the full listing-time metadata contract.
        assert {
            "created_at",
            "updated_at",
            "title",
            "type",
            "status",
            "primary_research_ref",
        } <= set(entry.metadata)
        assert entry.metadata["title"] == "Plan One"
        # Present-but-empty for a doc naming no parent: the key is never absent.
        assert entry.metadata["primary_research_ref"] == ""


async def test_list_metadata_carries_the_parent_ref(repo: Repository) -> None:
    # Sourced from the document, not the envelope — the one metadata field that is,
    # so a backend cannot populate the contract from envelope keys alone.
    child = _doc("p2") | {"research_refs": ["p1"], "primary_research_ref": "p1"}
    await _create(repo, "u1/demo/plan/p1", _doc("p1"))
    await _create(repo, "u1/demo/plan/p2", child)

    by_key = {e.key: e for e in await repo.list("u1/")}
    assert by_key["u1/demo/plan/p2"].metadata["primary_research_ref"] == "p1"
