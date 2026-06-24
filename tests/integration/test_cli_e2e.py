"""End-to-end CLI tests through Typer's CliRunner against the in-process app.

`build_client` is monkeypatched to return an ASGITransport-backed PlanClient (the
sync-portal bridge from conftest), so `runner.invoke` drives the whole command tree
into the real service without a socket, asserting on exit codes and stdout JSON.
"""

import json
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient

runner = CliRunner()

_VALID_CREATE = json.dumps(
    {
        "type": "plan",
        "slug": "p1",
        "title": "Plan One",
        "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
    }
)


@pytest.fixture
def patched_cli(client: PlanClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def build_client(url: str) -> PlanClient:
        return client

    monkeypatch.setattr(cli, "build_client", build_client)
    yield


def test_create_from_stdin_exits_ok_and_prints_slug(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["slug"] == "p1"
    assert "rev" in parsed
    assert "data" not in parsed


def test_get_missing_doc_exits_not_found(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["doc", "get", "demo", "ghost"])
    assert result.exit_code == 2


def test_stale_rev_toggle_exits_stale(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", "does-not-match"],
    )
    assert result.exit_code == 9


def test_malformed_from_json_exits_validation(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", '{"type":"plan"}'],
    )
    assert result.exit_code == 4


def test_foreign_uid_write_exits_forbidden(patched_cli: None) -> None:
    # Under noop auth the caller is always "dev"; a write to a foreign path-uid is
    # Forbidden (403 fires before the not-found read) -> exit 3.
    result = runner.invoke(
        cli.app, ["--uid", "evil", "doc", "status", "demo", "ghost", "active"]
    )
    assert result.exit_code == 3


def test_malformed_merge_patch_exits_validation(patched_cli: None) -> None:
    # Create a doc + section, then send invalid JSON to --merge-patch -> exit 4.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app,
        ["section", "patch", "demo", "p1", "ctx", "--merge-patch", "{bad"],
    )
    assert result.exit_code == 4


def test_create_full_flag_prints_full_doc(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        ["--full", "doc", "create", "demo", "--from-json", "-"],
        input=_VALID_CREATE,
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["slug"] == "p1"
    assert "rev" in parsed


def test_stale_rev_toggle_stderr_carries_current_rev(patched_cli: None) -> None:
    # Create doc, then attempt a toggle with a wrong rev -> exit 9 + JSON on stderr.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", "does-not-match"],
    )
    assert result.exit_code == 9
    err = json.loads(result.stderr)
    assert err["error"] == "stale_rev"
    assert err["current_rev"]


def test_task_toggle_default_prints_phase_tasks(patched_cli: None) -> None:
    # Create doc then toggle task 0; default output carries the affected phase.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    # Get the current rev from a get call.
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    rev = json.loads(get_result.stdout)["rev"]
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", rev],
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "phase" in parsed
    assert parsed["phase"]["slug"] == "a"
    assert isinstance(parsed["phase"]["tasks"], list)
    assert "data" not in parsed


def test_phase_move_default_prints_ordering(patched_cli: None) -> None:
    # Create doc with one phase, add a second, then move it.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    add_result = runner.invoke(cli.app, ["phase", "add", "demo", "p1", "b", "Beta"])
    rev = json.loads(add_result.stdout)["rev"]
    result = runner.invoke(
        cli.app, ["phase", "move", "demo", "p1", "b", "0", "--rev", rev]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "phases" in parsed
    assert [p["slug"] for p in parsed["phases"]] == ["b", "a"]
    assert "data" not in parsed
