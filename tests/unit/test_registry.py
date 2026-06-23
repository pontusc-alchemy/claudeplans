"""File-backed UserRegistry: minting, reload, idempotent ref-merge, lookups."""

import json
from pathlib import Path

from claudeplans.auth.identity import mint_uid
from claudeplans.auth.registry import UserRegistry


def _registry(tmp_path: Path) -> UserRegistry:
    return UserRegistry(tmp_path / "users.json")


def test_mint_creates_record_and_writes_file(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    rec = reg.mint("Alice Smith", ["a@x"])
    assert rec.uid == mint_uid("Alice Smith")
    assert rec.slug == "alice-smith"
    assert rec.identity_refs == ["a@x"]
    assert (tmp_path / "users.json").exists()


def test_reload_returns_the_record(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    rec = reg.mint("alice", ["a@x"])
    fresh = UserRegistry(tmp_path / "users.json")
    assert fresh.get(rec.uid) == rec


def test_mint_is_idempotent_and_merges_refs(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    first = reg.mint("alice", ["a@x"])
    second = reg.mint("alice", ["b@x"])
    assert second.uid == first.uid
    assert second.identity_refs == ["a@x", "b@x"]
    # Re-minting a known ref does not duplicate it.
    third = reg.mint("alice", ["a@x"])
    assert third.identity_refs == ["a@x", "b@x"]


def test_resolve_by_identity(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.mint("alice", ["a@x"])
    rec = reg.mint("alice", ["b@x"])
    assert reg.resolve_by_identity("b@x") == rec
    assert reg.resolve_by_identity("missing@x") is None


def test_resolve_by_identity_after_reload(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    rec = reg.mint("alice", ["a@x"])
    # A fresh registry reads the persisted file: identity lookups survive reload.
    fresh = UserRegistry(tmp_path / "users.json")
    resolved = fresh.resolve_by_identity("a@x")
    assert resolved is not None
    assert resolved.uid == rec.uid
    assert fresh.resolve_by_identity("missing@x") is None


def test_get_unknown_returns_none(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    assert reg.get("nope") is None


def test_on_disk_file_is_valid_json(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    rec = reg.mint("alice", ["a@x"])
    raw = json.loads((tmp_path / "users.json").read_text())
    assert raw[rec.uid]["uid"] == rec.uid
    assert raw[rec.uid]["slug"] == "alice"
    assert raw[rec.uid]["identity_refs"] == ["a@x"]
