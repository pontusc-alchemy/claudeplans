"""Core orchestration against a real FilesystemRepository.

Covers the two write disciplines: stable-key deltas bump rev without a client rev,
while index-addressed ops require the client's rev and surface StaleRevision (409).
"""

import json
from pathlib import Path

import pytest

from claudeplans import core
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans_contracts import (
    CorruptDocument,
    DocStatus,
    DocType,
    DocumentCreate,
    NotFound,
    Phase,
    PhaseStatus,
    StaleRevision,
    Task,
    key_for_document,
)


def _repo(tmp_path: Path) -> FilesystemRepository:
    return FilesystemRepository(tmp_path / "data")


def _create_in() -> DocumentCreate:
    return DocumentCreate(
        type=DocType.plan,
        slug="p1",
        title="Plan One",
        phases=[Phase(slug="a", name="Alpha", tasks=[Task(text="t1")])],
    )


async def test_create_then_get_round_trips(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    got_rev, got = await core.get_document(repo, key)
    assert got_rev == rev
    assert got.slug == "p1"
    assert got.owner_id == "u1"
    assert got.project == "demo"


async def test_stable_key_delta_bumps_rev_without_client_rev(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev1, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    rev2, updated = await core.set_phase_status(repo, key, "a", PhaseStatus.doing)
    assert rev2 != rev1
    assert updated.phases[0].status is PhaseStatus.doing


async def test_index_op_with_correct_rev_succeeds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev1, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    rev2, updated = await core.toggle_task(repo, key, "a", 0, True, rev1)
    assert rev2 != rev1
    assert updated.phases[0].tasks[0].checked is True


async def test_index_op_with_stale_rev_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    with pytest.raises(StaleRevision):
        await core.toggle_task(repo, key, "a", 0, True, "does-not-match")


async def test_delete_with_correct_rev(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev1, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    await core.delete_document(repo, key, rev1)
    with pytest.raises(NotFound):
        await core.get_document(repo, key)


async def test_delete_with_stale_rev_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    with pytest.raises(StaleRevision):
        await core.delete_document(repo, key, "does-not-match")


async def test_set_document_status_roundtrip(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    _, updated = await core.set_document_status(repo, key, DocStatus.active)
    assert updated.status is DocStatus.active


async def test_corrupt_non_integer_rev_raises_on_put(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in()
    )
    key = key_for_document(doc)
    # Hand-edit the on-disk rev to a non-integer; a subsequent put must surface a
    # clean CorruptDocument rather than a raw ValueError.
    path = tmp_path / "data" / f"{key}.json"
    envelope = json.loads(path.read_text())
    envelope["rev"] = "garbage"
    path.write_text(json.dumps(envelope))
    with pytest.raises(CorruptDocument):
        await core.toggle_task(repo, key, "a", 0, True, "garbage")
