"""Write-own authz at the single write path (core), against a real repository.

A caller may write only within its own namespace (write-own); reads are unrestricted.
"""

from pathlib import Path

import pytest

from claudeplans import core
from claudeplans.auth.provider import CurrentUser
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans_contracts import (
    DocStatus,
    DocType,
    DocumentCreate,
    Forbidden,
    NotFound,
    Phase,
    Task,
    key_for_document,
)

_OWNER = CurrentUser(uid="u1", name="u1", namespace="u1")
_EVIL = CurrentUser(uid="evil", name="evil", namespace="evil")


def _repo(tmp_path: Path) -> FilesystemRepository:
    return FilesystemRepository(tmp_path / "data")


def _create_in() -> DocumentCreate:
    return DocumentCreate(
        type=DocType.plan,
        slug="p1",
        title="Plan One",
        phases=[Phase(slug="a", name="Alpha", tasks=[Task(text="t1")])],
    )


async def test_owner_may_create_and_mutate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    _, updated = await core.set_document_status(
        repo, key, DocStatus.active, user=_OWNER
    )
    assert updated.status is DocStatus.active


async def test_create_in_foreign_namespace_is_forbidden(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(Forbidden):
        await core.create_document(
            repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_EVIL
        )


async def test_foreign_write_delta_is_forbidden(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    with pytest.raises(Forbidden):
        await core.set_document_status(repo, key, DocStatus.active, user=_EVIL)
    # The matching owner still succeeds.
    _, updated = await core.set_document_status(
        repo, key, DocStatus.active, user=_OWNER
    )
    assert updated.status is DocStatus.active


async def test_reads_are_unrestricted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    # get_document takes no user: reads are read-all.
    _, got = await core.get_document(repo, key)
    assert got.slug == "p1"


async def test_authz_precedes_stale_revision(tmp_path: Path) -> None:
    # The write-own guard fires before the rev check: a foreign caller with a
    # garbage rev gets Forbidden, never StaleRevision.
    repo = _repo(tmp_path)
    _, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    with pytest.raises(Forbidden):
        await core.toggle_task(repo, key, "a", 0, True, "stale-rev", user=_EVIL)


async def test_authz_precedes_not_found(tmp_path: Path) -> None:
    # The guard fires before the read: a foreign caller writing to a non-existent
    # key gets Forbidden, never NotFound (key owner "ghost" != _EVIL namespace).
    repo = _repo(tmp_path)
    with pytest.raises(Forbidden):
        await core.set_document_status(
            repo, "ghost/demo/x", DocStatus.active, user=_EVIL
        )


async def test_foreign_delete_is_forbidden_owner_succeeds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    with pytest.raises(Forbidden):
        await core.delete_document(repo, key, rev, user=_EVIL)
    # The matching owner deletes successfully; the doc is then gone.
    await core.delete_document(repo, key, rev, user=_OWNER)
    with pytest.raises(NotFound):
        await core.get_document(repo, key)


async def test_foreign_index_op_is_forbidden(tmp_path: Path) -> None:
    # _write_at_rev guard with an otherwise-valid rev: the foreign caller still 403s.
    repo = _repo(tmp_path)
    rev, doc = await core.create_document(
        repo, owner_id="u1", project="demo", doc_in=_create_in(), user=_OWNER
    )
    key = key_for_document(doc)
    with pytest.raises(Forbidden):
        await core.move_phase(repo, key, "a", 0, rev, user=_EVIL)
