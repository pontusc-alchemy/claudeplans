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


async def test_get_unparseable_json_raises_corrupt(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    path = tmp_path / "data" / "u1" / "demo" / "plan" / "p1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    with pytest.raises(CorruptDocument):
        await repo.get("u1/demo/plan/p1")


async def test_put_over_unparseable_json_raises_corrupt(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    path = tmp_path / "data" / "u1" / "demo" / "plan" / "p1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    with pytest.raises(CorruptDocument):
        await repo.put("u1/demo/plan/p1", {}, "1")


async def test_delete_over_unparseable_json_raises_corrupt(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    path = tmp_path / "data" / "u1" / "demo" / "plan" / "p1.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json")
    with pytest.raises(CorruptDocument):
        await repo.delete("u1/demo/plan/p1", "1")


async def test_get_non_object_json_raises_corrupt(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    path = tmp_path / "data" / "u1" / "demo" / "plan" / "p1.json"
    path.parent.mkdir(parents=True)
    # Valid JSON but not an object: parses, then .get() would AttributeError.
    path.write_text("[1, 2, 3]")
    with pytest.raises(CorruptDocument):
        await repo.get("u1/demo/plan/p1")
