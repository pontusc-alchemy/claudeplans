"""A file-backed user registry (`users.json`): name -> stable uid + identity refs.

Synchronous on purpose: minting is rare and off the dev hot path (the no-op
provider never touches it). The deferred IAP provider will cache/offload this so
the JWT path does not pay a disk read per request. The on-disk write mirrors the
atomic temp-file + os.replace discipline used by storage/filesystem.py so a reader
never observes a half-written registry.
"""

import json
import os
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .identity import mint_uid, slugify


class UserRecord(BaseModel):
    """One registered user: stable uid, source name/slug, and verified identity refs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: str
    name: str
    slug: str
    identity_refs: list[str] = Field(default_factory=list)


class UserRegistry:
    """Loads/stores UserRecords keyed by uid in a single JSON object file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._users: dict[str, UserRecord] = self._load()

    def _load(self) -> dict[str, UserRecord]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text())
        return {uid: UserRecord.model_validate(rec) for uid, rec in raw.items()}

    def mint(self, name: str, identity_refs: Sequence[str] = ()) -> UserRecord:
        """Register `name` (idempotent): same name -> same uid; refs union-merged.

        A repeat mint unions the new identity_refs into the existing record
        preserving first-seen order, persisting only when the set actually changes.
        """
        uid = mint_uid(name)
        existing = self._users.get(uid)
        if existing is not None:
            merged = list(dict.fromkeys([*existing.identity_refs, *identity_refs]))
            if merged != existing.identity_refs:
                existing = existing.model_copy(update={"identity_refs": merged})
                self._users[uid] = existing
                self._save()
            return existing
        record = UserRecord(
            uid=uid,
            name=name,
            slug=slugify(name),
            identity_refs=list(dict.fromkeys(identity_refs)),
        )
        self._users[uid] = record
        self._save()
        return record

    def get(self, uid: str) -> UserRecord | None:
        """The record for `uid`, or None if unregistered."""
        return self._users.get(uid)

    def resolve_by_identity(self, identity_ref: str) -> UserRecord | None:
        """The first record carrying `identity_ref`, or None."""
        for record in self._users.values():
            if identity_ref in record.identity_refs:
                return record
        return None

    def _save(self) -> None:
        """Atomically rewrite `users.json` (temp file + os.replace)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {uid: rec.model_dump(mode="json") for uid, rec in self._users.items()}
        tmp = self._path.with_name(f"{self._path.name}.tmp")
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, self._path)
