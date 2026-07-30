"""`doc create-many` — N cold starts collapse to one, prefix semantics preserved."""

import json

import pytest
from _cli import runner
from typer.testing import Result

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


def _body(slug: str, **extra: object) -> dict[str, object]:
    return {"type": "plan", "slug": slug, "title": slug.upper()} | extra


def _run(*bodies: dict[str, object]) -> Result:
    return runner.invoke(
        cli.app,
        ["doc", "create-many", "demo", "--from-json", "-"],
        input=json.dumps(list(bodies)),
    )


def _slugs_in_project() -> set[str]:
    listed = runner.invoke(cli.app, ["doc", "list", "demo"])
    return {i["slug"] for i in json.loads(listed.stdout)["data"]["items"]}


@pytest.mark.usefixtures("patched_cli")
def test_parent_and_children_land_in_one_call() -> None:
    """The run-003 shape: links are fields, so this is 3 creates and zero link calls."""
    result = _run(
        _body("root", type="research"),
        _body("kid-a", research_refs=["root"], primary_research_ref="root"),
        _body("kid-b", research_refs=["root"], primary_research_ref="root"),
    )
    assert result.exit_code == ExitCode.OK, result.stderr
    out = json.loads(result.stdout)
    assert (out["created"], out["failed"], out["skipped"]) == (3, 0, 0)
    assert [op["result"] for op in out["ops"]] == ["created"] * 3
    assert [op["i"] for op in out["ops"]] == [0, 1, 2]
    assert out["ops"][0]["rev"] == "1"
    assert out["ops"][1]["view_url"].endswith("/projects/demo/docs/kid-a/view")
    assert _slugs_in_project() == {"root", "kid-a", "kid-b"}


@pytest.mark.usefixtures("patched_cli")
def test_preflight_rejects_the_whole_batch_before_any_write() -> None:
    """A shape error in a later body must cost zero writes, not a partial apply."""
    result = _run(_body("ok-one"), _body("ok-two"), {"type": "plan", "slug": "bad"})
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert err["op_index"] == 2
    assert result.stdout == ""
    assert _slugs_in_project() == set()


@pytest.mark.usefixtures("patched_cli")
def test_failure_mid_batch_applies_a_prefix_and_exits_partial() -> None:
    """Exit 7 is the only nonzero code that does NOT mean "nothing landed"."""
    _run(_body("taken"))
    result = _run(_body("first"), _body("taken"), _body("never"))
    assert result.exit_code == ExitCode.PARTIAL
    out = json.loads(result.stdout)
    assert (out["created"], out["failed"], out["skipped"]) == (1, 1, 1)
    assert [op["result"] for op in out["ops"]] == ["created", "failed", "skipped"]
    assert out["ops"][1]["error"]["conflict"] == "exists"
    # A skipped op is guaranteed unattempted, so resuming is a tail of the array.
    assert "never" not in _slugs_in_project()
    assert "first" in _slugs_in_project()


@pytest.mark.usefixtures("patched_cli")
def test_first_op_failing_reports_that_ops_own_code() -> None:
    """Nothing landed, so the batch is indistinguishable from the single-op verb."""
    _run(_body("taken"))
    result = _run(_body("taken"), _body("never"))
    assert result.exit_code == ExitCode.STALE_REV
    out = json.loads(result.stdout)
    assert (out["created"], out["failed"], out["skipped"]) == (0, 1, 1)
    assert "never" not in _slugs_in_project()


@pytest.mark.usefixtures("patched_cli")
def test_per_op_error_is_byte_identical_to_the_single_op_verb() -> None:
    """The whole point of a batch is that one branch reads both.

    Compared as serialized bytes, not as dicts, because key order is part of what a
    caller diffs when it re-pipes a failed batch through `doc create`.
    """
    _run(_body("taken"))
    single = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", "-"],
        input=json.dumps(_body("taken")),
    )
    assert single.exit_code == ExitCode.STALE_REV
    batch = _run(_body("fresh"), _body("taken"))
    op_error = json.loads(batch.stdout)["ops"][1]["error"]
    assert json.dumps(op_error, separators=(",", ":")) == single.stderr.strip()


@pytest.mark.usefixtures("patched_cli")
def test_empty_array_is_a_no_op_not_an_error() -> None:
    result = _run()
    assert result.exit_code == ExitCode.OK
    assert json.loads(result.stdout) == {
        "created": 0,
        "failed": 0,
        "skipped": 0,
        "ops": [],
    }
