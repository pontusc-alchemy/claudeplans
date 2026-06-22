"""The async Repository seam: the storage contract every backend implements.

CAS (compare-and-set) is explicit: each object carries an opaque `rev`; a write
declares the rev it expects (or CREATE for create-if-absent), and a mismatch
raises StaleRevision. Blocking IO is offloaded to a threadpool inside each
adapter, never on the event loop. The filesystem adapter lands in the storage
phase; GCS slots in behind this same interface during the cloud migration.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final


class _Create:
    """Type of the CREATE sentinel.

    A private singleton type so `str | _Create` is a real union the type checker
    can narrow on `is CREATE`; a bare `object` would erase the distinction.
    """

    __slots__ = ()


# Sentinel for create-if-absent writes (no prior rev expected).
CREATE: Final[_Create] = _Create()


@dataclass(frozen=True, slots=True)
class ListEntry:
    """One entry from a prefix listing: the key, its current rev, and metadata."""

    key: str
    rev: str
    metadata: dict[str, str] = field(default_factory=dict)


class Repository(ABC):
    """Async store of JSON documents with compare-and-set writes."""

    @abstractmethod
    async def get(self, key: str) -> tuple[str, dict[str, Any]]:
        """Return (rev, raw document). Raise NotFound if absent."""

    @abstractmethod
    async def put(
        self, key: str, document: dict[str, Any], expected_rev: str | _Create
    ) -> str:
        """Write `document` if the stored rev matches `expected_rev` (or CREATE).

        Return the new rev. Raise StaleRevision on a rev mismatch.
        """

    @abstractmethod
    async def delete(self, key: str, expected_rev: str) -> None:
        """Delete `key` if its rev matches; raise StaleRevision/NotFound otherwise."""

    @abstractmethod
    async def list(self, prefix: str) -> Iterable[ListEntry]:
        """List entries under `prefix` (the adapter paginates internally)."""
