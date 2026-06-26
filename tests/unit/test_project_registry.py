"""File-backed ProjectRegistry: set/reload round-trip, per-user keying, names_for."""

import json
from pathlib import Path

from claudeplans.projects import ProjectRegistry


def _registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(tmp_path / "projects.json")


def test_set_and_get_round_trip(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "myproj", "My Project")
    assert reg.get("alice", "myproj") == "My Project"
    assert (tmp_path / "projects.json").exists()


def test_reload_returns_the_name(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "myproj", "My Project")
    fresh = ProjectRegistry(tmp_path / "projects.json")
    assert fresh.get("alice", "myproj") == "My Project"


def test_get_unknown_returns_none(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    assert reg.get("alice", "nope") is None


def test_get_absent_file_returns_none(tmp_path: Path) -> None:
    reg = ProjectRegistry(tmp_path / "nonexistent.json")
    assert reg.get("alice", "proj") is None


def test_per_user_keying_is_independent(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "proj", "Alice's Project")
    reg.set("bob", "proj", "Bob's Project")
    assert reg.get("alice", "proj") == "Alice's Project"
    assert reg.get("bob", "proj") == "Bob's Project"


def test_on_disk_json_shape(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "proj", "Alice's Project")
    raw = json.loads((tmp_path / "projects.json").read_text())
    assert raw == {"alice/proj": "Alice's Project"}


def test_names_for_filters_by_owner(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "projA", "Alice A")
    reg.set("alice", "projB", "Alice B")
    reg.set("bob", "projA", "Bob A")

    alice_names = reg.names_for("alice")
    assert alice_names == {"projA": "Alice A", "projB": "Alice B"}

    bob_names = reg.names_for("bob")
    assert bob_names == {"projA": "Bob A"}


def test_names_for_empty_when_no_match(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.set("alice", "proj", "Alice's Project")
    assert reg.names_for("bob") == {}
