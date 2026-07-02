"""CLI end-to-end tests for the `meta` command group."""

import json
import os

import httpx
import pytest
from _cli import runner

from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient


@pytest.mark.usefixtures("patched_cli")
def test_schema_command_shape() -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "enums" in parsed
    assert "exit_codes" in parsed
    assert "error_kinds" in parsed
    assert "invalid_rev" in parsed["error_kinds"]
    assert "envelopes" in parsed
    assert "commands" in parsed
    enums = parsed["enums"]
    assert "doc_status" in enums
    assert "doc_type" in enums
    assert "phase_status" in enums
    assert "plan" in enums["doc_type"]
    assert "research" in enums["doc_type"]
    # Enum members
    assert "draft" in enums["doc_status"]
    assert "active" in enums["doc_status"]
    assert "done" in enums["doc_status"]
    assert "todo" in enums["phase_status"]
    assert "doing" in enums["phase_status"]
    assert "done" in enums["phase_status"]
    assert "blocked" in enums["phase_status"]
    # section_placement vocabulary is part of the machine-readable contract.
    assert enums["section_placement"] == ["lead", "trail"]
    # Exit code values
    exit_codes = parsed["exit_codes"]
    assert exit_codes["not_found"] == 5
    assert exit_codes["transport"] == 6


@pytest.mark.usefixtures("patched_cli")
def test_schema_conditional_writes_and_list_envelope() -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "conditional_writes" in parsed
    cw = parsed["conditional_writes"]
    assert isinstance(cw, list)
    # Known conditional-write commands that carry a REQUIRED --rev.
    assert "doc delete" in cw
    assert "phase move" in cw
    assert "section move" in cw
    assert "task toggle" in cw
    # set-checked's --rev is optional (needed only for the explicit-index form, not
    # --all), so it is NOT unconditionally rev-gated and stays out of the list.
    assert "task set-checked" not in cw
    # List envelope shape documented.
    assert "list" in parsed["envelopes"]
    # Move index semantics documented in the agent-facing contract.
    assert "move_index" in parsed
    # Command aliases/equivalences documented in the agent-facing contract.
    assert parsed["aliases"]["doc set-status"] == "doc status"
    assert "task toggle <i>" in parsed["equivalences"]


@pytest.mark.usefixtures("patched_cli")
def test_schema_command_flags_and_global_flags() -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    cf = parsed["command_flags"]
    assert "task add" in cf
    # Only leaf commands are keyed — the bare group is not.
    assert "task" not in cf
    add_flags = cf["task add"]
    # Bool toggle shows BOTH forms (proves secondary_opts is merged) + its type.
    checked = next(f for f in add_flags if f["opts"] == ["--checked"])
    assert checked["secondary_opts"] == ["--unchecked"]
    assert checked["kind"] == "option"
    assert checked["type"] == "boolean"
    # A plain (non-required) option carries its value type so an agent can author it.
    at = next(f for f in add_flags if f["opts"] == ["--at"])
    assert at["kind"] == "option"
    assert at["required"] is False
    assert at["type"] == "integer"
    # phase add gained --at, mirroring task/section add.
    phase_at = next(f for f in cf["phase add"] if f["opts"] == ["--at"])
    assert phase_at["required"] is False
    assert phase_at["type"] == "integer"
    # Arguments are tagged argument-vs-option, marked required, and typed.
    project = next(f for f in add_flags if f["opts"] == ["project"])
    assert project["kind"] == "argument"
    assert project["required"] is True
    assert project["type"] == "text"
    # Root global flags live in their own key, excluding Typer completion boilerplate.
    gf_opts = {tuple(f["opts"]) for f in parsed["global_flags"]}
    assert ("--url",) in gf_opts
    assert ("--uid",) in gf_opts
    assert ("--full", "-v") in gf_opts
    assert ("--install-completion",) not in gf_opts
    assert ("--show-completion",) not in gf_opts
    assert not any("--version" in f["opts"] for f in parsed["global_flags"])
    # The task-add reply envelope is now advertised.
    assert "write_task_add" in parsed["envelopes"]


def test_no_color_help_has_no_ansi() -> None:
    import subprocess
    import sys

    env = {**os.environ, "NO_COLOR": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "claudeplans_cli", "--help"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"claudeplans_cli --help exited {result.returncode}: {result.stderr}"
    )
    assert result.stdout, "claudeplans_cli --help produced no output"
    assert "Usage" in result.stdout, (
        "Expected 'Usage' in --help output; got: " + result.stdout[:200]
    )
    assert "\x1b[" not in result.stdout, (
        "ANSI escape sequences found in --help output with NO_COLOR=1"
    )


def test_version_flag_exits_zero_and_prints_version() -> None:
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("claudeplans ")
    tokens = result.stdout.split()
    assert len(tokens) >= 2
    assert tokens[1]


@pytest.mark.usefixtures("patched_cli")
def test_doctor_reports_reachable() -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["reachable"] is True
    # `url` reflects the env/config-resolved value — assert it's a non-empty string.
    assert isinstance(parsed["url"], str) and parsed["url"]
    assert parsed["uid"] == "dev"
    # /status returns identity fields; the in-process app surfaces auth_mode.
    assert "auth_mode" in parsed


def test_doctor_reports_unreachable_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A down server: every request refused. doctor exercises the real
    # health() -> get() -> raise_for_status() path and reports reachable:false,
    # exit 0, with a detail string — never a traceback (house MockTransport style).
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    down_client = PlanClient(
        http_client=httpx.Client(
            base_url="http://t", transport=httpx.MockTransport(refuse)
        )
    )
    monkeypatch.setattr(cli, "build_client", lambda _url: down_client)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["reachable"] is False
    assert parsed["detail"]


def test_doctor_non_2xx_reports_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server that responds with 503 — HTTPStatusError branch. doctor must still
    # exit 0 and report reachable:false with a truthy detail string.
    def always_503(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    down_client = PlanClient(
        http_client=httpx.Client(
            base_url="http://t", transport=httpx.MockTransport(always_503)
        )
    )
    monkeypatch.setattr(cli, "build_client", lambda _url: down_client)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["reachable"] is False
    assert parsed["detail"]


def test_doctor_bad_url_no_traceback() -> None:
    # A malformed URL whose host fails IDNA resolution at request-build time.
    # Uses the REAL build_client (no patched_cli) so httpx.InvalidURL is raised
    # inside health() and caught by the broad except in doctor. Regression guard
    # for the IDNA-at-request-build crash — no network needed.
    result = runner.invoke(cli.app, ["--url", "http://xn--/x", "doctor"])
    assert result.exit_code == 0
    assert "Traceback" not in result.stdout
    assert "Traceback" not in (result.stderr or "")
    assert json.loads(result.stdout)["reachable"] is False
