"""Corrupt-envelope hardening: malformed files surface CorruptDocument, not 500s."""

import json
from pathlib import Path

import pytest

from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans_contracts import CorruptDocument


async def test_get_missing_document_key_raises_corrupt(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # Hand-write a file whose envelope lacks the "document" key.
    path = tmp_path / "data" / "u1" / "demo" / "plan" / "p1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rev": "1", "created_at": "now", "updated_at": "now"}))
    with pytest.raises(CorruptDocument):
        await repo.get("u1/demo/plan/p1")
