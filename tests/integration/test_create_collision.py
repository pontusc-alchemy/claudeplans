"""A duplicate-slug create is legible end to end, not a bare stale_rev."""

import json

import pytest
from _cli import VALID_CREATE, runner

from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_duplicate_slug_create_reports_conflict_and_names_the_key() -> None:
    """`doc create` takes no --rev, so the 409's documented remedy is unexecutable.

    The marker has to ride from the server, which knows a create lost to an existing
    key rather than a write's target vanishing, all the way to stderr.
    """
    first = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    assert first.exit_code == ExitCode.OK, first.stderr
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    assert result.exit_code == ExitCode.STALE_REV
    err = json.loads(result.stderr)
    assert err["error"] == "stale_rev"
    assert err["conflict"] == "exists"
    # detail names the colliding key; the 409 carries no rev to identify it by.
    assert err["detail"].endswith("/demo/p1")
    assert err["current_rev"] == ""


@pytest.mark.usefixtures("patched_cli")
def test_ordinary_stale_rev_carries_no_conflict_marker() -> None:
    """A real CAS loss stays unmarked and retryable.

    Without this half, branching on the marker could misroute a retryable conflict
    into "give up" the day something else starts setting it.
    """
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "toggle", "demo", "p1", "a", "0", "--rev", "99"]
    )
    assert result.exit_code == ExitCode.STALE_REV
    err = json.loads(result.stderr)
    assert err["error"] == "stale_rev"
    assert "conflict" not in err
    assert err["current_rev"] == "1"
