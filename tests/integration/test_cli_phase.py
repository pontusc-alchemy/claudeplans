"""CLI end-to-end tests for the `phase` command group."""

import json
from pathlib import Path

import pytest
from _cli import VALID_CREATE, assert_validation_exit, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_phase_move_default_prints_ordering() -> None:
    # Create doc with one phase, add a second, then move it.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
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


@pytest.mark.usefixtures("patched_cli")
def test_add_phase_path_corrupting_slug_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["phase", "add", "demo", "p1", "bad/slug", "Name"])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_name_renames() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["phase", "set", "demo", "p1", "a", "--name", "Alpha Renamed"]
    )
    assert result.exit_code == 0
    # Verify via doc get that the phase name changed.
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    phases = doc["data"]["phases"]
    assert phases[0]["name"] == "Alpha Renamed"


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_at_inserts_at_front() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["phase", "add", "demo", "p1", "z", "Zeta", "--at", "0"]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    phases = [p["slug"] for p in doc["data"]["phases"]]
    assert phases[0] == "z"
    assert phases[1] == "a"


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_at_out_of_range_exits_validation() -> None:
    # An out-of-range --at surfaces as a clean exit 4, not a 500 or silent append.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["phase", "add", "demo", "p1", "z", "Zeta", "--at", "99"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_prose_flags_persist() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "phase",
            "set",
            "demo",
            "p1",
            "a",
            "--intro",
            "Why this phase",
            "--exit-criteria",
            "All checks pass",
            "--notes",
            "A revision note",
        ],
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    phase = json.loads(get_result.stdout)["data"]["phases"][0]
    assert phase["intro"] == "Why this phase"
    assert phase["exit_criteria"] == "All checks pass"
    assert phase["notes"] == "A revision note"


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_help_lists_prose_options() -> None:
    import re

    # Force a wide terminal so Typer doesn't truncate option names with an ellipsis
    # (the default 80-col render is width-fragile).
    result = runner.invoke(cli.app, ["phase", "set", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--intro" in plain
    assert "--exit-criteria" in plain
    assert "--notes" in plain


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_intro_empty_string_clears() -> None:
    # '' is sent (not omitted), so it clears a previously-set field — the CLI-layer
    # invariant the help advertises and that exclude_none must preserve.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["phase", "set", "demo", "p1", "a", "--intro", "seeded"])
    result = runner.invoke(cli.app, ["phase", "set", "demo", "p1", "a", "--intro", ""])
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert json.loads(get_result.stdout)["data"]["phases"][0]["intro"] == ""


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_intro_file_reads_from_file(tmp_path: Path) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    f = tmp_path / "intro.md"
    f.write_text("Prose with an apostrophe: container's lifecycle.\n\nSecond para.")
    result = runner.invoke(
        cli.app, ["phase", "set", "demo", "p1", "a", "--intro-file", str(f)]
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    intro = json.loads(get_result.stdout)["data"]["phases"][0]["intro"]
    assert "container's lifecycle" in intro
    assert "Second para." in intro


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_notes_file_stdin() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "set", "demo", "p1", "a", "--notes-file", "-"],
        input="!!! note\n    A card from stdin.",
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    notes = json.loads(get_result.stdout)["data"]["phases"][0]["notes"]
    assert "A card from stdin." in notes


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_inline_and_file_conflict_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "set", "demo", "p1", "a", "--intro", "x", "--intro-file", "/tmp/x"],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_phase_set_missing_file_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "set", "demo", "p1", "a", "--notes-file", "/nonexistent/nope.md"],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_non_utf8_file_exits_validation(tmp_path: Path) -> None:
    # A non-UTF-8 --*-file must surface as a clean validation error (exit 4),
    # never an uncaught UnicodeDecodeError traceback (the "never a traceback"
    # contract). UnicodeDecodeError is a ValueError, not an OSError.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"\xff\xfe\x00binary")
    result = runner.invoke(
        cli.app,
        ["phase", "add", "demo", "p1", "ph9", "Name", "--intro-file", str(bad)],
    )
    assert result.exit_code == ExitCode.VALIDATION
    assert result.exception is None or isinstance(result.exception, SystemExit)


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_prose_flags_persist() -> None:
    # Create a doc, then add a phase with all three prose flags in one call.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "phase",
            "add",
            "demo",
            "p1",
            "ph2",
            "Phase Two",
            "--intro",
            "X",
            "--exit-criteria",
            "Y",
            "--notes",
            "Z",
        ],
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    phases = {p["slug"]: p for p in doc["data"]["phases"]}
    assert "ph2" in phases
    assert phases["ph2"]["intro"] == "X"
    assert phases["ph2"]["exit_criteria"] == "Y"
    assert phases["ph2"]["notes"] == "Z"


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_without_prose_defaults_to_empty() -> None:
    # A phase add without prose flags must store intro/exit_criteria/notes as "".
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["phase", "add", "demo", "p1", "ph3", "Phase Three"]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    phases = {p["slug"]: p for p in doc["data"]["phases"]}
    assert phases["ph3"]["intro"] == ""
    assert phases["ph3"]["exit_criteria"] == ""
    assert phases["ph3"]["notes"] == ""


@pytest.mark.usefixtures("patched_cli")
def test_phase_complete_checks_all_and_sets_done() -> None:
    # `phase complete` checks every task and sets status=done in one rev-free call.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    # Add a 2nd task (left unchecked).
    runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "t2"])
    result = runner.invoke(cli.app, ["phase", "complete", "demo", "p1", "a"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["phase"]["status"] == "done"
    assert all(t["checked"] is True for t in parsed["phase"]["tasks"])


_PHASE_WITH_TASKS = json.dumps(
    {
        "slug": "b",
        "name": "Beta",
        "status": "doing",
        "tasks": [{"text": "first"}, {"text": "second", "checked": True}],
        "intro": "Intro prose",
    }
)


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_from_json_lands_tasks_in_one_rev() -> None:
    """Nine writes collapse to one: the phase, its prose and its tasks together."""
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "add", "demo", "p1", "--from-json", "-"],
        input=_PHASE_WITH_TASKS,
    )
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["rev"] == "2"
    phases = json.loads(runner.invoke(cli.app, ["doc", "phases", "demo", "p1"]).stdout)
    added = next(p for p in phases["phases"] if p["slug"] == "b")
    assert added["status"] == "doing"
    assert added["intro"] == "Intro prose"
    assert [(t["text"], t["checked"]) for t in added["tasks"]] == [
        ("first", False),
        ("second", True),
    ]


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_without_slug_or_name_exits_validation() -> None:
    # A domain error (exit 4) with a message, not Typer's exit-2 usage box: the
    # args are only optional because --from-json can carry them.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["phase", "add", "demo", "p1"])
    assert_validation_exit(result)
    assert "--from-json" in json.loads(result.stderr)["detail"]


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_from_json_body_wins_over_positional_args() -> None:
    # Documented in --help: the body carries everything, so the positionals are
    # ignored rather than half-merged.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "add", "demo", "p1", "ignored", "Ignored", "--from-json", "-"],
        input=_PHASE_WITH_TASKS,
    )
    assert result.exit_code == 0, result.stderr
    phases = json.loads(runner.invoke(cli.app, ["doc", "phases", "demo", "p1"]).stdout)
    assert [p["slug"] for p in phases["phases"]] == ["a", "b"]


@pytest.mark.usefixtures("patched_cli")
def test_phase_add_from_json_rejects_an_unknown_field() -> None:
    # AddPhaseRequest forbids extras, so a typo'd key fails client-side before any
    # request rather than landing a phase missing what the author meant to write.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    body = json.dumps({"slug": "b", "name": "Beta", "task": [{"text": "typo"}]})
    result = runner.invoke(cli.app, ["phase", "add", "demo", "p1", "--from-json", body])
    assert_validation_exit(result)
