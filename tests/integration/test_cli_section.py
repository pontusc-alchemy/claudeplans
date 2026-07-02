"""CLI end-to-end tests for the `section` command group."""

import json
from pathlib import Path

import pytest
from _cli import VALID_CREATE, assert_validation_exit, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_malformed_merge_patch_exits_validation() -> None:
    # Create a doc + section, then send invalid JSON to --merge-patch -> exit 4.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app,
        ["section", "patch", "demo", "p1", "ctx", "--merge-patch", "{bad"],
    )
    assert result.exit_code == 4


@pytest.mark.usefixtures("patched_cli")
def test_add_section_reserved_anchor_exits_validation() -> None:
    # The '@end' footgun is rejected at the boundary, not stored verbatim.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["section", "add", "demo", "p1", "@end", "Heading"])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_section_move_reorders() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    # Add two sections, then move the second to index 0.
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "first", "First"])
    add_result = runner.invoke(
        cli.app, ["section", "add", "demo", "p1", "second", "Second"]
    )
    rev = json.loads(add_result.stdout)["rev"]
    result = runner.invoke(
        cli.app, ["section", "move", "demo", "p1", "second", "0", "--rev", rev]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert [s["anchor"] for s in doc["data"]["sections"]] == ["second", "first"]


@pytest.mark.usefixtures("patched_cli")
def test_section_add_at_inserts() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    # Add one section first, then insert a second one at index 0.
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "existing", "Existing"])
    result = runner.invoke(
        cli.app, ["section", "add", "demo", "p1", "pre", "Pre", "--at", "0"]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    anchors = [s["anchor"] for s in doc["data"]["sections"]]
    assert anchors[0] == "pre"
    assert anchors[1] == "existing"


@pytest.mark.usefixtures("patched_cli")
def test_section_move_stale_rev_exits_stale() -> None:
    # `section move` is position-sensitive: a wrong --rev is a 409 -> exit 9, proving
    # the route's If-Match gate is wired (regression guard for dropping IfMatchDep).
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "first", "First"])
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "second", "Second"])
    result = runner.invoke(
        cli.app,
        ["section", "move", "demo", "p1", "second", "0", "--rev", "999999999"],
    )
    assert result.exit_code == ExitCode.STALE_REV


@pytest.mark.usefixtures("patched_cli")
def test_section_add_placement_flag_persists() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["section", "add", "demo", "p1", "ctx", "Context", "--placement", "trail"],
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    section = json.loads(get_result.stdout)["data"]["sections"][0]
    assert section["placement"] == "trail"


@pytest.mark.usefixtures("patched_cli")
def test_section_add_help_lists_placement_choices() -> None:
    import re

    result = runner.invoke(
        cli.app, ["section", "add", "--help"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--placement" in plain
    # The StrEnum choices render as a [lead|trail] metavar — assert the joined form
    # so this proves the choices are discoverable, not just the word in the prose.
    assert "lead|trail" in plain


@pytest.mark.usefixtures("patched_cli")
def test_section_add_invalid_placement_exits_usage() -> None:
    # A bad enum CHOICE is a Typer parse-time usage error (exit 2), distinct from a
    # parseable-but-invalid value that reaches the server as a 422 (exit 4).
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["section", "add", "demo", "p1", "ctx", "Context", "--placement", "sideways"],
    )
    assert result.exit_code == ExitCode.USAGE


@pytest.mark.usefixtures("patched_cli")
def test_section_set_placement_flag_persists() -> None:
    # The set path (vs add) drives --placement through runner.invoke end to end.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app, ["section", "set", "demo", "p1", "ctx", "--placement", "trail"]
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert json.loads(get_result.stdout)["data"]["sections"][0]["placement"] == "trail"


@pytest.mark.usefixtures("patched_cli")
def test_section_set_body_file_reads_from_file(tmp_path: Path) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    f = tmp_path / "body.md"
    f.write_text("Prose with an apostrophe: container's lifecycle.\n\nSecond para.")
    result = runner.invoke(
        cli.app, ["section", "set", "demo", "p1", "ctx", "--body-file", str(f)]
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    body = json.loads(get_result.stdout)["data"]["sections"][0]["body"]
    assert "container's lifecycle" in body
    assert "Second para." in body


@pytest.mark.usefixtures("patched_cli")
def test_section_add_body_file_stdin() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "section",
            "add",
            "demo",
            "p1",
            "stdin-anchor",
            "Stdin Heading",
            "--body-file",
            "-",
        ],
        input="!!! note\n    A card from stdin.",
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    sections = json.loads(get_result.stdout)["data"]["sections"]
    bodies = [s["body"] for s in sections if s["anchor"] == "stdin-anchor"]
    assert bodies and "A card from stdin." in bodies[0]


@pytest.mark.usefixtures("patched_cli")
def test_section_set_body_inline_and_file_conflict_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app,
        ["section", "set", "demo", "p1", "ctx", "--body", "x", "--body-file", "/tmp/x"],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_section_set_missing_body_file_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app,
        ["section", "set", "demo", "p1", "ctx", "--body-file", "/nonexistent/nope.md"],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_section_add_no_body_defaults_empty() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["section", "add", "demo", "p1", "empty-body", "Empty Heading"]
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    sections = json.loads(get_result.stdout)["data"]["sections"]
    bodies = [s["body"] for s in sections if s["anchor"] == "empty-body"]
    assert bodies and bodies[0] == ""


@pytest.mark.usefixtures("patched_cli")
def test_section_add_body_inline_and_file_conflict_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "section",
            "add",
            "demo",
            "p1",
            "conflict-anchor",
            "Conflict Heading",
            "--body",
            "x",
            "--body-file",
            "/tmp/x",
        ],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_section_add_missing_body_file_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "section",
            "add",
            "demo",
            "p1",
            "missing-file-anchor",
            "Missing File Heading",
            "--body-file",
            "/nonexistent/nope.md",
        ],
    )
    assert result.exit_code == ExitCode.VALIDATION
