"""The default local backend: one JSON file per key under a root directory.

Each file holds an ENVELOPE, not a bare document: ``{rev, created_at, updated_at,
document}``. The ``rev`` is a monotonic integer-as-string counter that doubles as
the compare-and-set token — a deterministic counter, so a stale write is detected
by a plain string mismatch. ``created_at``/``updated_at`` are envelope metadata,
never model fields.

Blocking file IO is offloaded to a threadpool via ``anyio.to_thread.run_sync`` so
it never stalls the event loop. Writes are atomic (temp file + ``os.replace``), so
a reader never observes a half-written file. A per-key ``asyncio.Lock`` makes the
read -> compare -> write sequence atomic WITHIN this process; the single-worker
server is the documented assumption, and multi-process safety is deferred behind
the GCS backend.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anyio import to_thread

from claudeplans_contracts import NotFound, StaleRevision

from .repository import CREATE, ListEntry, Repository, _Create


def _read_envelope(path: Path) -> dict[str, Any]:
    """Load the envelope at `path`. Raises FileNotFoundError if absent."""
    with path.open("rb") as fh:
        return json.loads(fh.read())


def _write_envelope_atomic(path: Path, envelope: dict[str, Any]) -> None:
    """Write `envelope` to `path` atomically (temp file beside it, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(json.dumps(envelope).encode())
            fh.flush()
            os.fsync(fh.fileno())
        # os.replace is atomic, so a reader never sees a half-written file.
        os.replace(tmp, path)
    except BaseException:
        # The temp file would otherwise leak on any failure before the rename.
        Path(tmp).unlink(missing_ok=True)
        raise


def _create_envelope_exclusive(path: Path, envelope: dict[str, Any]) -> None:
    """Create `path` only if absent (O_EXCL). Raises FileExistsError otherwise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(json.dumps(envelope).encode())
        fh.flush()
        os.fsync(fh.fileno())


def _walk_keys(root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Return (key, envelope) for every *.json under `root`, keyed POSIX-relative."""
    found: list[tuple[str, dict[str, Any]]] = []
    for path in root.rglob("*.json"):
        try:
            envelope = _read_envelope(path)
        except FileNotFoundError, json.JSONDecodeError:
            # Deleted mid-walk or corrupt on disk: omit from the listing rather than
            # failing the whole list() — a single bad file must not 500 the index.
            continue
        key = path.relative_to(root).with_suffix("").as_posix()
        found.append((key, envelope))
    return found


class FilesystemRepository(Repository):
    """Repository backed by one JSON envelope file per key under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self._root: Path = Path(root)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        # Lazily create+cache the per-key lock. Safe without a meta-lock: there is no
        # await between the dict read and write, so asyncio's single thread cannot
        # interleave another coroutine here.
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _path_for(self, key: str) -> Path:
        path = self._root / f"{key}.json"
        # A key that escapes the root is a programming error (keys are derived, not
        # user-supplied), not a domain error — so guard with ValueError, not NotFound.
        if not path.resolve().is_relative_to(self._root.resolve()):
            raise ValueError(f"key {key!r} escapes the storage root")
        return path

    async def get(self, key: str) -> tuple[str, dict[str, Any]]:
        path = self._path_for(key)
        try:
            envelope = await to_thread.run_sync(_read_envelope, path)
        except FileNotFoundError:
            raise NotFound(key) from None
        return envelope["rev"], envelope["document"]

    async def put(
        self, key: str, document: dict[str, Any], expected_rev: str | _Create
    ) -> str:
        path = self._path_for(key)
        now = datetime.now(UTC).isoformat()
        async with self._lock_for(key):
            if expected_rev is CREATE:
                envelope = {
                    "rev": "1",
                    "created_at": now,
                    "updated_at": now,
                    "document": document,
                }
                try:
                    await to_thread.run_sync(_create_envelope_exclusive, path, envelope)
                except FileExistsError:
                    # Create-if-absent lost: another writer created the key first.
                    raise StaleRevision(key) from None
                return "1"

            try:
                current = await to_thread.run_sync(_read_envelope, path)
            except FileNotFoundError:
                # The rev you hold no longer exists: a lost race, not a NotFound.
                raise StaleRevision(key) from None
            if current["rev"] != expected_rev:
                raise StaleRevision(key)
            new_rev = str(int(current["rev"]) + 1)
            envelope = {
                "rev": new_rev,
                "created_at": current["created_at"],
                "updated_at": now,
                "document": document,
            }
            await to_thread.run_sync(_write_envelope_atomic, path, envelope)
            return new_rev

    async def delete(self, key: str, expected_rev: str) -> None:
        path = self._path_for(key)
        async with self._lock_for(key):
            try:
                current = await to_thread.run_sync(_read_envelope, path)
            except FileNotFoundError:
                raise NotFound(key) from None
            if current["rev"] != expected_rev:
                raise StaleRevision(key)
            await to_thread.run_sync(path.unlink)

    async def list(self, prefix: str) -> Iterable[ListEntry]:
        found = await to_thread.run_sync(_walk_keys, self._root)
        entries: list[ListEntry] = []
        for key, env in found:
            if not key.startswith(prefix):
                continue
            doc = env["document"]
            # Surface title/type/status as metadata so the search phase can build a
            # title index without reading bodies (GCS sources these from object meta).
            entries.append(
                ListEntry(
                    key=key,
                    rev=env["rev"],
                    metadata={
                        "created_at": env["created_at"],
                        "updated_at": env["updated_at"],
                        "title": str(doc.get("title", "")),
                        "type": str(doc.get("type", "")),
                        "status": str(doc.get("status", "")),
                    },
                )
            )
        return entries
