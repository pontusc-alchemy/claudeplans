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


def test_create_from_stdin_exits_ok_and_prints_doc(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["slug"] == "p1"


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
