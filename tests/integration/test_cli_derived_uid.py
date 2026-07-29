"""The derived-uid gate driven end to end against a noop-auth server — proving
the shipped default is unchanged and that turning the gate on cannot write."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from claudeplans_cli import cli
from claudeplans_cli.identity import _CI_MARKERS, DERIVE_GATE, FLOOR
from claudeplans_contracts import ExitCode

runner = CliRunner()

_PLAN = json.dumps({"type": "plan", "slug": "p1", "title": "Plan One"})


@pytest.fixture(autouse=True)
def hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No config file, no inherited env, and a home that derives to `alek`."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("CLAUDEPLANS_URL", raising=False)
    monkeypatch.delenv("CLAUDEPLANS_UID", raising=False)
    monkeypatch.delenv(DERIVE_GATE, raising=False)
    # Scrubbed from the source list, not a copy: on a CI runner these are set,
    # derivation abstains, and every gate-on expectation below would floor.
    for marker in _CI_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/alek")))
    yield


def _create(project: str) -> Result:
    args = ["doc", "create", project, "--from-json", "-"]
    return runner.invoke(cli.app, args, input=_PLAN)


def test_gate_off_writes_land_in_the_floor_namespace(patched_cli: None) -> None:
    """The shipped default, unchanged by this feature."""
    assert _create("proj").exit_code == ExitCode.OK
    shown = runner.invoke(cli.app, ["config", "show"])
    assert json.loads(shown.stdout)["uid"] == FLOOR


def test_gate_on_targets_derived_namespace_and_is_refused(
    patched_cli: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing claim: derivation reaches the wire, and noop refuses it."""
    monkeypatch.setenv(DERIVE_GATE, "1")

    shown = runner.invoke(cli.app, ["config", "show"])
    assert json.loads(shown.stdout)["uid"] == "alek"

    # noop resolves every caller to the fixed dev user, so can_write compares
    # "dev" against "alek" and refuses where the floor would have succeeded.
    assert _create("proj").exit_code == ExitCode.FORBIDDEN


def test_gate_on_still_reads_because_reads_take_no_auth(patched_cli: None) -> None:
    """Reads, listings and view URLs work under a derived uid; only writes 403."""
    assert _create("proj").exit_code == ExitCode.OK
    listed = runner.invoke(cli.app, ["--uid", "alek", "doc", "list", "proj"])
    assert listed.exit_code == ExitCode.OK


@pytest.mark.parametrize("marker", sorted(_CI_MARKERS))
def test_a_ci_marker_floors_the_uid_even_with_the_gate_on(
    patched_cli: None, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    """CI has no human identity, so the gate cannot derive one there."""
    monkeypatch.setenv(DERIVE_GATE, "1")
    monkeypatch.setenv(marker, "true")
    shown = runner.invoke(cli.app, ["config", "show"])
    assert json.loads(shown.stdout)["uid"] == FLOOR
    # Flooring means the write is allowed again — this is what turned #28 red
    # when the fixture left the runner's own markers in place.
    assert _create("proj").exit_code == ExitCode.OK


def test_explicit_uid_overrides_the_gate(
    patched_cli: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit intent outranks derivation, so `--uid dev` still writes."""
    monkeypatch.setenv(DERIVE_GATE, "1")
    args = ["--uid", FLOOR, "doc", "create", "proj", "--from-json", "-"]
    assert runner.invoke(cli.app, args, input=_PLAN).exit_code == ExitCode.OK
