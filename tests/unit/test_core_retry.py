"""read_modify_write CAS-retry: success, transient retry, and budget exhaustion."""

from collections.abc import Iterable
from typing import Any

import pytest

from claudeplans import core
from claudeplans.auth.provider import CurrentUser
from claudeplans.core import read_modify_write
from claudeplans.storage.repository import ListEntry, Repository, _Create
from claudeplans_contracts import DocStatus, DocType, Document, NotFound, StaleRevision

# The retry tests address key "k", so write-own requires namespace == owner_of("k").
_USER = CurrentUser(uid="u1", name="u1", namespace="k")


class _FakeRepo(Repository):
    """In-memory repo whose `put` raises StaleRevision its first `stale_until` calls.

    Only `get`/`put` are exercised by read_modify_write; `delete`/`list` exist to
    satisfy the ABC and assert loud if the code under test ever reaches them.
    """

    def __init__(self, stale_until: int, *, not_found_on_reread: bool = False) -> None:
        self._stale_until: int = stale_until
        self._not_found_on_reread: bool = not_found_on_reread
        self.put_calls: int = 0
        self.get_calls: int = 0

    async def get(self, key: str) -> tuple[str, dict[str, Any]]:
        self.get_calls += 1
        # The post-exhaustion re-read is the only get beyond the retry budget; give it
        # a DIFFERENT rev (or simulate a concurrent deletion) so a test can tell a
        # genuine re-read from a reused stale loop variable.
        is_reread = self.get_calls > core.MAX_WRITE_RETRIES
        if is_reread and self._not_found_on_reread:
            raise NotFound(key)
        doc = Document(
            type=DocType.plan,
            project="demo",
            slug="p1",
            title="Plan One",
            owner_id="u1",
        )
        return ("7" if is_reread else "1"), doc.model_dump(mode="json")

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
    new_rev, updated = await read_modify_write(repo, "k", _activate, user=_USER)
    assert new_rev == "2"
    assert updated.status is DocStatus.active
    assert repo.put_calls == 1


async def test_transient_stale_then_success() -> None:
    repo = _FakeRepo(stale_until=2)
    new_rev, updated = await read_modify_write(repo, "k", _activate, user=_USER)
    assert new_rev == "2"
    assert updated.status is DocStatus.active
    # Two stale rejections, then the third put succeeds.
    assert repo.put_calls == 3


async def test_budget_exhausted_raises() -> None:
    repo = _FakeRepo(stale_until=core.MAX_WRITE_RETRIES)
    with pytest.raises(StaleRevision) as excinfo:
        await read_modify_write(repo, "k", _activate, user=_USER)
    assert repo.put_calls == core.MAX_WRITE_RETRIES
    # The 409 must still carry a usable rev (a fresh re-read after the budget is
    # spent), so an agent can retry without a separate GET — the "retry without
    # re-read" promise. "7" is the re-read rev, distinct from the loop's "1": this
    # proves a genuine re-read, not a reused stale loop variable.
    assert excinfo.value.current_rev == "7"


async def test_budget_exhausted_reread_not_found_propagates() -> None:
    # If the key is deleted mid-contention, the post-exhaustion re-read raises
    # NotFound (-> 404), which is the truthful outcome rather than a misleading 409.
    repo = _FakeRepo(stale_until=core.MAX_WRITE_RETRIES, not_found_on_reread=True)
    with pytest.raises(NotFound):
        await read_modify_write(repo, "k", _activate, user=_USER)
    assert repo.put_calls == core.MAX_WRITE_RETRIES
