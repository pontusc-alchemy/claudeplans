"""CLI end-to-end tests for the `task` command group."""

import json

import pytest
from _cli import VALID_CREATE, assert_validation_exit, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_stale_rev_toggle_exits_stale() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", "999999999"],
    )
    assert result.exit_code == 9


@pytest.mark.usefixtures("patched_cli")
def test_stale_rev_toggle_stderr_carries_current_rev() -> None:
    # Create doc, then attempt a toggle with a wrong rev -> exit 9 + JSON on stderr.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", "999999999"],
    )
    assert result.exit_code == 9
    err = json.loads(result.stderr)
    assert err["error"] == "stale_rev"
    assert err["current_rev"]


@pytest.mark.usefixtures("patched_cli")
def test_task_toggle_default_prints_phase_tasks() -> None:
    # Create doc then toggle task 0; default output carries the affected phase.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
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


@pytest.mark.usefixtures("patched_cli")
def test_add_task_empty_text_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "   "])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_edit_task_empty_text_exits_validation() -> None:
    # edit_task mutates via model_copy (no field validator); the rejection comes from
    # core's whole-document re-validation before persist. Belt-and-suspenders for that
    # model_copy path, distinct from the eager-construction add_* paths.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "edit", "demo", "p1", "a", "0", "   ", "--rev", rev]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_task_add_at_inserts_at_front() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "add", "demo", "p1", "a", "first", "--at", "0"]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    assert tasks[0]["text"] == "first"
    assert tasks[1]["text"] == "t1"


@pytest.mark.usefixtures("patched_cli")
def test_task_set_checked_sets_state() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "--rev", rev]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["phases"][0]["tasks"][0]["checked"] is True


@pytest.mark.usefixtures("patched_cli")
def test_task_set_checked_is_idempotent() -> None:
    # Asserting the same absolute state twice stays True (not a flip) — each call uses
    # the rev returned by the previous one.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    first = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "--rev", rev]
    )
    assert first.exit_code == 0
    rev2 = json.loads(first.stdout)["rev"]
    second = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "--rev", rev2]
    )
    assert second.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["phases"][0]["tasks"][0]["checked"] is True


@pytest.mark.usefixtures("patched_cli")
def test_task_add_append_emits_index() -> None:
    # VALID_CREATE already has one task ("t1") in phase "a".
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "t2"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "warnings" in parsed
    assert "task" in parsed
    assert parsed["task"]["phase"] == "a"
    # Prior length was 1 (task "t1"), so appended index is 1.
    assert parsed["task"]["index"] == 1
    assert "data" not in parsed


@pytest.mark.usefixtures("patched_cli")
def test_task_add_at_emits_index() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "add", "demo", "p1", "a", "inserted", "--at", "0"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["task"]["phase"] == "a"
    assert parsed["task"]["index"] == 0
    # Insert derives index from --at (not len-1); confirm the echo reads the
    # inserted task at slot 0, not the neighbour shifted out of it.
    assert parsed["task"]["text"] == "inserted"
    assert parsed["task"]["checked"] is False
    assert "data" not in parsed


@pytest.mark.usefixtures("patched_cli")
def test_task_add_checked_flag_creates_checked_task() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "add", "demo", "p1", "a", "pre-done", "--checked"]
    )
    assert result.exit_code == 0
    # Self-verifying: the add reply itself echoes the created task's text+checked,
    # so no follow-up `doc get` is needed to confirm the checked-at-creation state.
    parsed = json.loads(result.stdout)
    assert parsed["task"]["text"] == "pre-done"
    assert parsed["task"]["checked"] is True
    assert "data" not in parsed
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    added = tasks[-1]
    assert added["text"] == "pre-done"
    assert added["checked"] is True


@pytest.mark.usefixtures("patched_cli")
def test_task_add_default_is_unchecked() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "plain-task"])
    assert result.exit_code == 0
    # The slim add reply echoes text + checked=False without a follow-up read.
    parsed = json.loads(result.stdout)
    assert parsed["task"]["text"] == "plain-task"
    assert parsed["task"]["checked"] is False
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    added = tasks[-1]
    assert added["text"] == "plain-task"
    assert added["checked"] is False


@pytest.mark.usefixtures("patched_cli")
def test_task_add_index_is_addressable_by_set_checked() -> None:
    # VALID_CREATE has one task in phase "a", so an append lands at index 1.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    add_result = runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "new-task"])
    assert add_result.exit_code == 0
    add_parsed = json.loads(add_result.stdout)
    task_index = add_parsed["task"]["index"]
    rev = add_parsed["rev"]

    # Use the rev and index from the add reply directly — no extra read needed.
    set_result = runner.invoke(
        cli.app,
        [
            "task",
            "set-checked",
            "demo",
            "p1",
            "a",
            str(task_index),
            "--rev",
            rev,
        ],
    )
    assert set_result.exit_code == 0

    # Verify the correct task is now checked (the one at task_index, not index 0).
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    assert tasks[task_index]["checked"] is True, (
        f"Expected tasks[{task_index}] to be checked=True"
    )
    # The original task at index 0 must be untouched (its default is False).
    assert tasks[0]["checked"] is False, (
        "tasks[0] should not have been affected by set-checked on tasks[task_index]"
    )


@pytest.mark.usefixtures("patched_cli")
def test_task_add_second_index_advances() -> None:
    # After two appends the indices are 1 and 2 respectively.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    first_add = json.loads(
        runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "task-b"]).stdout
    )
    # task add is unconditional (no --rev); just append a second task.
    second_add = json.loads(
        runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "task-c"]).stdout
    )
    assert second_add["task"]["index"] == first_add["task"]["index"] + 1

    # set-checked on the second appended index must land on the right task.
    set_result = runner.invoke(
        cli.app,
        [
            "task",
            "set-checked",
            "demo",
            "p1",
            "a",
            str(second_add["task"]["index"]),
            "--rev",
            second_add["rev"],
        ],
    )
    assert set_result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    assert tasks[second_add["task"]["index"]]["checked"] is True
    assert tasks[first_add["task"]["index"]]["checked"] is False


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_all_checks_every_task_rev_free() -> None:
    # --all targets every task without requiring a rev.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    # Add a 2nd task so there are two to check.
    runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "t2"])
    result = runner.invoke(cli.app, ["task", "set-checked", "demo", "p1", "a", "--all"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "phase" in parsed
    assert "status" in parsed["phase"]
    assert all(t["checked"] is True for t in parsed["phase"]["tasks"])


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_all_unchecked_clears_every_task() -> None:
    # First check all, then clear all — both rev-free.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["task", "set-checked", "demo", "p1", "a", "--all"])
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "--all", "--unchecked"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert all(t["checked"] is False for t in parsed["phase"]["tasks"])


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_multi_index_checks_those() -> None:
    # Explicit index list is position-sensitive and requires --rev; only the named
    # indices flip — the omitted one stays unchecked (proves selective, not check-all).
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "t2"])
    runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "t3"])
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "2", "--rev", rev]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    tasks = parsed["phase"]["tasks"]
    assert tasks[0]["checked"] is True
    assert tasks[1]["checked"] is False
    assert tasks[2]["checked"] is True


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_multi_index_requires_rev_exits_validation() -> None:
    # Explicit indices without --rev must be rejected at the CLI layer.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "set-checked", "demo", "p1", "a", "0"])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_all_and_indices_conflict_exits_validation() -> None:
    # Passing both explicit indices and --all is a usage error.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "--all"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_no_target_exits_validation() -> None:
    # No indices and no --all is a usage error.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "set-checked", "demo", "p1", "a"])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_index_out_of_range_exits_validation() -> None:
    # An out-of-range index must surface as a 422 -> exit VALIDATION.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "99", "--rev", rev]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_set_checked_multi_index_stale_rev_exits_stale() -> None:
    # A wrong rev with explicit indices must surface as a 409 -> exit STALE_REV.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["task", "set-checked", "demo", "p1", "a", "0", "--rev", "999999999"],
    )
    assert result.exit_code == ExitCode.STALE_REV


@pytest.mark.usefixtures("patched_cli")
def test_toggle_phase_slice_includes_status() -> None:
    # Regression guard: the phase slice emitted by toggle now always contains status.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "toggle", "demo", "p1", "a", "0", "--rev", rev]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "status" in parsed["phase"]
