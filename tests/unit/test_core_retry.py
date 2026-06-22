"""read_modify_write CAS-retry: success, transient retry, and budget exhaustion."""

from collections.abc import Iterable
from typing import Any

import pytest

from claudeplans import core
from claudeplans.core import read_modify_write
from claudeplans.storage.repository import ListEntry, Repository, _Create
from claudeplans_contracts import DocStatus, DocType, Document, StaleRevision


class _FakeRepo(Repository):
    """In-memory repo whose `put` raises StaleRevision its first `stale_until` calls.

    Only `get`/`put` are exercised by read_modify_write; `delete`/`list` exist to
    satisfy the ABC and assert loud if the code under test ever reaches them.
    """

    def __init__(self, stale_until: int) -> None:
        self._stale_until: int = stale_until
        self.put_calls: int = 0

    async def get(self, key: str) -> tuple[str, dict[str, Any]]:
        doc = Document(
            type=DocType.plan,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
        )
        return "1", doc.model_dump(mode="json")

    async def put(
        self, key: str, document: dict[str, Any], expected_rev: str | _Create
    ) -> str:
        self.put_calls += 1
        if self.put_calls <= self._stale_until:
            raise StaleRevision(key)
        return "2"

    async def delete(self, key: str, expected_rev: str) -> None:
        raise AssertionError("delete must not be called by read_modify_write")

    async def list(self, prefix: str) -> Iterable[ListEntry]:
        raise AssertionError("list must not be called by read_modify_write")


def _activate(doc: Document) -> Document:
    # Absolute set, not a relative flip, so re-applying after a re-read is safe.
    return doc.model_copy(update={"status": DocStatus.active})


async def test_success_on_first_try() -> None:
    repo = _FakeRepo(stale_until=0)
    new_rev, updated = await read_modify_write(repo, "k", _activate)
    assert new_rev == "2"
    assert updated.status is DocStatus.active
    assert repo.put_calls == 1


async def test_transient_stale_then_success() -> None:
    repo = _FakeRepo(stale_until=2)
    new_rev, updated = await read_modify_write(repo, "k", _activate)
    assert new_rev == "2"
    assert updated.status is DocStatus.active
    # Two stale rejections, then the third put succeeds.
    assert repo.put_calls == 3


async def test_budget_exhausted_raises() -> None:
    repo = _FakeRepo(stale_until=core.MAX_WRITE_RETRIES)
    with pytest.raises(StaleRevision):
        await read_modify_write(repo, "k", _activate)
    assert repo.put_calls == core.MAX_WRITE_RETRIES
