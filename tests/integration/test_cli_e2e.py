"""End-to-end CLI tests through Typer's CliRunner against the in-process app.

`build_client` is monkeypatched to return an ASGITransport-backed PlanClient (the
sync-portal bridge from conftest), so `runner.invoke` drives the whole command tree
into the real service without a socket, asserting on exit codes and stdout JSON.
"""

import json
import os
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from typer.testing import CliRunner, Result

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient
from claudeplans_contracts import ExitCode

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
    assert result.exit_code == ExitCode.NOT_FOUND
    err = json.loads(result.stderr)
    assert err["error"] == "not_found"


def test_usage_error_exits_two_distinct_from_not_found(patched_cli: None) -> None:
    # A malformed command line (missing the required slug arg) is Typer/Click usage
    # -> exit 2, which NOT_FOUND (5) no longer collides with.
    result = runner.invoke(cli.app, ["doc", "get", "demo"])
    assert result.exit_code == ExitCode.USAGE
    assert result.exit_code != ExitCode.NOT_FOUND


def test_service_down_exits_transport_no_traceback(
    client: PlanClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A transport failure (here: every request refused) is a structured error on
    # stderr with the dedicated exit code, never a stacktrace.
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    down_client = PlanClient(
        http_client=httpx.Client(
            base_url="http://t", transport=httpx.MockTransport(refuse)
        )
    )
    monkeypatch.setattr(cli, "build_client", lambda url: down_client)
    result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert result.exit_code == ExitCode.TRANSPORT
    err = json.loads(result.stderr)
    assert err["error"] == "transport"
    assert "Traceback" not in result.stderr


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


# Each invalid-input path is a clean exit 4 (VALIDATION) with a structured stderr
# error, never a 500 / traceback and never a silent write.
def _assert_validation_exit(result: Result) -> None:
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"


def test_add_section_reserved_anchor_exits_validation(patched_cli: None) -> None:
    # The '@end' footgun is rejected at the boundary, not stored verbatim.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["section", "add", "demo", "p1", "@end", "Heading"])
    _assert_validation_exit(result)


def test_add_phase_path_corrupting_slug_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["phase", "add", "demo", "p1", "bad/slug", "Name"])
    _assert_validation_exit(result)


def test_add_task_empty_text_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["task", "add", "demo", "p1", "a", "   "])
    _assert_validation_exit(result)


def test_create_empty_title_exits_validation(patched_cli: None) -> None:
    # DocumentCreate has no title validator; the server's Document compose rejects it.
    body = json.dumps({"type": "plan", "slug": "p2", "title": ""})
    result = runner.invoke(cli.app, ["doc", "create", "demo", "--from-json", body])
    _assert_validation_exit(result)


def test_edit_task_empty_text_exits_validation(patched_cli: None) -> None:
    # edit_task mutates via model_copy (no field validator); the rejection comes from
    # core's whole-document re-validation before persist. Belt-and-suspenders for that
    # model_copy path, distinct from the eager-construction add_* paths.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "edit", "demo", "p1", "a", "0", "   ", "--rev", rev]
    )
    _assert_validation_exit(result)


# --- phase set --name --------------------------------------------------------


def test_phase_set_name_renames(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["phase", "set", "demo", "p1", "a", "--name", "Alpha Renamed"]
    )
    assert result.exit_code == 0
    # Verify via doc get that the phase name changed.
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    phases = doc["data"]["phases"]
    assert phases[0]["name"] == "Alpha Renamed"


# --- section move --rev ------------------------------------------------------


def test_section_move_reorders(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


# --- task add --at 0 ---------------------------------------------------------


def test_task_add_at_inserts_at_front(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "add", "demo", "p1", "a", "first", "--at", "0"]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    assert tasks[0]["text"] == "first"
    assert tasks[1]["text"] == "t1"


# --- section add --at --------------------------------------------------------


def test_section_add_at_inserts(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


# --- task set-checked --------------------------------------------------------


def test_task_set_checked_sets_state(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    result = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "true", "--rev", rev]
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["phases"][0]["tasks"][0]["checked"] is True


# --- doc set (omit-to-leave) -------------------------------------------------


def test_doc_set_title_and_description(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["doc", "set", "demo", "p1", "--title", "New Title", "--description", "Desc"],
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["title"] == "New Title"
    assert doc["data"]["description"] == "Desc"


def test_doc_set_title_only_leaves_description(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    # First set both fields.
    runner.invoke(
        cli.app,
        ["doc", "set", "demo", "p1", "--title", "T1", "--description", "D1"],
    )
    # Second call changes only title; description must survive.
    result = runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--title", "T2"])
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["title"] == "T2"
    assert doc["data"]["description"] == "D1"


def test_doc_set_frontmatter_invalid_json_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "set", "demo", "p1", "--frontmatter", "{bad"]
    )
    _assert_validation_exit(result)


def test_doc_set_empty_title_exits_validation(patched_cli: None) -> None:
    # `doc set --title ""` must reject via the phase-2 validator (re-validation on
    # persist), not silently blank the title.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--title", ""])
    _assert_validation_exit(result)


def test_task_set_checked_is_idempotent(patched_cli: None) -> None:
    # Asserting the same absolute state twice stays True (not a flip) — each call uses
    # the rev returned by the previous one.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    rev = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)["rev"]
    first = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "true", "--rev", rev]
    )
    assert first.exit_code == 0
    rev2 = json.loads(first.stdout)["rev"]
    second = runner.invoke(
        cli.app, ["task", "set-checked", "demo", "p1", "a", "0", "true", "--rev", rev2]
    )
    assert second.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["phases"][0]["tasks"][0]["checked"] is True


def test_section_move_stale_rev_exits_stale(patched_cli: None) -> None:
    # `section move` is position-sensitive: a wrong --rev is a 409 -> exit 9, proving
    # the route's If-Match gate is wired (regression guard for dropping IfMatchDep).
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "first", "First"])
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "second", "Second"])
    result = runner.invoke(
        cli.app,
        ["section", "move", "demo", "p1", "second", "0", "--rev", "does-not-match"],
    )
    assert result.exit_code == ExitCode.STALE_REV


# ---------------------------------------------------------------------------
# Feature 1: search (CLI `claudeplans search <project> <query>`)
# Search needs lifespan (the index is async), so drive the CLI via a live
# uvicorn server instead of the in-process SyncASGITransport.
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_url(tmp_path: Path) -> Iterator[str]:
    """Run a live uvicorn server and yield its base URL."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_search_finds_doc_by_title(live_url: str) -> None:
    # Create a doc via HTTP, then poll the search index (async refresh) before
    # driving the CLI against the same live server.
    import time

    base = live_url
    with httpx.Client(base_url=base) as http:
        http.post(
            "/v1/users/dev/projects/demo/docs",
            json=json.loads(_VALID_CREATE),
        )
        # Poll until the index is populated (async refresh).
        for _ in range(100):
            r = http.get("/v1/users/dev/projects/demo/search", params={"q": "Plan One"})
            if r.status_code == 200 and r.json().get("hits"):
                break
            time.sleep(0.02)

    # Now drive the CLI against the live server.
    result = runner.invoke(cli.app, ["--url", base, "search", "demo", "Plan One"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["hits"]
    slugs = [h["slug"] for h in parsed["data"]["hits"]]
    assert "p1" in slugs


def test_search_miss_returns_empty_hits(live_url: str) -> None:
    # A query that matches nothing still exits 0 and returns an empty hits list.
    import time

    base = live_url
    with httpx.Client(base_url=base) as http:
        http.post(
            "/v1/users/dev/projects/demo/docs",
            json=json.loads(_VALID_CREATE),
        )
        # Wait for the index to be ready (poll on the known title).
        for _ in range(100):
            r = http.get("/v1/users/dev/projects/demo/search", params={"q": "Plan One"})
            if r.status_code == 200 and r.json().get("hits"):
                break
            time.sleep(0.02)

    result = runner.invoke(
        cli.app, ["--url", base, "search", "demo", "xyzzy-no-match-ever"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["hits"] == []


def test_search_phase_name_returns_phase_kind_hit(live_url: str) -> None:
    # _VALID_CREATE has phase name "Alpha"; searching for it should surface a hit
    # with kind == "phase", exercising the section/phase index branch.
    import time

    base = live_url
    with httpx.Client(base_url=base) as http:
        http.post(
            "/v1/users/dev/projects/demo/docs",
            json=json.loads(_VALID_CREATE),
        )
        # Poll until the phase name is indexed.
        for _ in range(100):
            r = http.get("/v1/users/dev/projects/demo/search", params={"q": "Alpha"})
            if r.status_code == 200 and r.json().get("hits"):
                break
            time.sleep(0.02)

    result = runner.invoke(cli.app, ["--url", base, "search", "demo", "Alpha"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["hits"]
    kinds = [h["kind"] for h in parsed["data"]["hits"]]
    assert "phase" in kinds


# ---------------------------------------------------------------------------
# Feature 2: project lineage JSON
# ---------------------------------------------------------------------------


def test_project_lineage_json_shape(patched_cli: None) -> None:
    # Create a plan doc; lineage should have research+unlinked_plans keys.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    lineage = parsed["data"]
    assert "research" in lineage
    assert "unlinked_plans" in lineage
    # The plan (no primary_research_ref) lands in unlinked_plans.
    slugs = [p["slug"] for p in lineage["unlinked_plans"]]
    assert "p1" in slugs


def test_project_lineage_linked_plan_appears_under_research_node(
    patched_cli: None,
) -> None:
    # Create a research doc and a plan that cites it as primary; the plan must
    # appear under the research node's `plans` list and NOT in `unlinked_plans`.
    research_body = json.dumps({"type": "research", "slug": "r1", "title": "R One"})
    plan_body = json.dumps(
        {
            "type": "plan",
            "slug": "pl1",
            "title": "Plan",
            "primary_research_ref": "r1",
            "research_refs": ["r1"],
        }
    )
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=research_body
    )
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=plan_body
    )
    result = runner.invoke(cli.app, ["project", "lineage", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    lineage = parsed["data"]
    # Research node for r1 must exist and contain pl1 in plans.
    research_nodes = {n["slug"]: n for n in lineage["research"]}
    assert "r1" in research_nodes
    plan_slugs_under_r1 = [p["slug"] for p in research_nodes["r1"]["plans"]]
    assert "pl1" in plan_slugs_under_r1
    # pl1 must NOT appear in unlinked_plans.
    unlinked_slugs = [p["slug"] for p in lineage["unlinked_plans"]]
    assert "pl1" not in unlinked_slugs


# ---------------------------------------------------------------------------
# Feature 3: doc rev
# ---------------------------------------------------------------------------


def test_doc_rev_returns_non_empty_rev(patched_cli: None) -> None:
    create_result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    create_rev = json.loads(create_result.stdout)["rev"]
    result = runner.invoke(cli.app, ["doc", "rev", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert parsed["rev"]  # non-empty string
    # The rev must match what the create reply reported.
    assert parsed["rev"] == create_rev


def test_doc_rev_missing_doc_exits_not_found(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["doc", "rev", "demo", "ghost"])
    assert result.exit_code == ExitCode.NOT_FOUND
    err = json.loads(result.stderr)
    assert err["error"] == "not_found"


# ---------------------------------------------------------------------------
# Feature 4: doc list --type filter
# ---------------------------------------------------------------------------

_VALID_RESEARCH = json.dumps({"type": "research", "slug": "r1", "title": "R One"})


def test_doc_list_type_filter_research_only(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", "-"],
        input=_VALID_RESEARCH,
    )
    result = runner.invoke(cli.app, ["doc", "list", "demo", "--type", "research"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    slugs = [i["slug"] for i in parsed["data"]["items"]]
    assert "r1" in slugs
    assert "p1" not in slugs


def test_doc_list_type_filter_plan_only(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", "-"],
        input=_VALID_RESEARCH,
    )
    result = runner.invoke(cli.app, ["doc", "list", "demo", "--type", "plan"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    slugs = [i["slug"] for i in parsed["data"]["items"]]
    assert "p1" in slugs
    assert "r1" not in slugs


# ---------------------------------------------------------------------------
# Feature 5: schema flat command
# ---------------------------------------------------------------------------


def test_schema_command_shape(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "enums" in parsed
    assert "exit_codes" in parsed
    assert "error_kinds" in parsed
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


# ---------------------------------------------------------------------------
# Feature 6: create reply includes type
# ---------------------------------------------------------------------------


def test_create_reply_includes_type(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed.get("type") == "plan"


# ---------------------------------------------------------------------------
# Phase 5 "output-consistency" — new tests
# ---------------------------------------------------------------------------


# Task 1: doc delete emits {rev, warnings}
def test_doc_delete_emits_rev_warnings(patched_cli: None) -> None:
    create_result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    rev = json.loads(create_result.stdout)["rev"]
    result = runner.invoke(cli.app, ["doc", "delete", "demo", "p1", "--rev", rev])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "warnings" in parsed
    assert "deleted" not in parsed


# Task 1: doc list emits {data, warnings}
def test_doc_list_emits_data_warnings_envelope(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "list", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    assert isinstance(parsed["warnings"], list)


# Task 1: doc phases emits {rev, phases, warnings}
def test_doc_phases_includes_warnings(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "phases", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "phases" in parsed
    assert "warnings" in parsed
    assert isinstance(parsed["warnings"], list)


# Task 2: --fields with unknown key exits 4 with {"error":"validation"}
def test_doc_get_unknown_field_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--fields", "no_such_field"]
    )
    _assert_validation_exit(result)


# Task 2: --section with absent anchor exits 4 with {"error":"validation"}
def test_doc_get_absent_section_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--section", "no_such_anchor"]
    )
    _assert_validation_exit(result)


# Task 2: --phase with absent slug exits 4 with {"error":"validation"}
def test_doc_get_absent_phase_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--phase", "no_such_phase"]
    )
    _assert_validation_exit(result)


# Task 3: doc set-status alias works identically to doc status
def test_doc_set_status_alias_works(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "set-status", "demo", "p1", "active"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "warnings" in parsed
    # Verify the status actually changed.
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["status"] == "active"


# Task 5: schema command includes conditional_writes and list envelope
def test_schema_conditional_writes_and_list_envelope(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["schema"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "conditional_writes" in parsed
    cw = parsed["conditional_writes"]
    assert isinstance(cw, list)
    # Known conditional-write commands that carry --rev.
    assert "doc delete" in cw
    assert "phase move" in cw
    assert "section move" in cw
    assert "task set-checked" in cw
    # List envelope shape documented.
    assert "list" in parsed["envelopes"]


# Task 6: linking a non-existent research ref exits 4 (validation)
def test_doc_link_nonexistent_ref_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "link", "demo", "p1", "ghost_ref"])
    _assert_validation_exit(result)


# Task 6: linking a real research doc in same project succeeds
def test_doc_link_real_research_ref_succeeds(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", "-"],
        input=_VALID_RESEARCH,
    )
    result = runner.invoke(cli.app, ["doc", "link", "demo", "p1", "r1"])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Phase 6 "scaffolding-ergonomics" -- tasks 1-4
# ---------------------------------------------------------------------------

_NESTED_CREATE = json.dumps(
    {
        "type": "plan",
        "slug": "nested",
        "title": "Nested Doc",
        "sections": [{"anchor": "intro", "heading": "Intro"}],
        "phases": [
            {
                "slug": "ph1",
                "name": "Phase 1",
                "tasks": [{"text": "do x"}, {"text": "do y"}],
            }
        ],
    }
)


# Task 1: doc create --from-json with nested sections+phases+tasks scaffolds
# the full document in one call.
def test_create_from_json_full_scaffold(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_NESTED_CREATE
    )
    assert result.exit_code == 0
    # Fetch the created doc and verify all nested structure is present.
    doc_result = runner.invoke(cli.app, ["doc", "get", "demo", "nested"])
    assert doc_result.exit_code == 0
    doc = json.loads(doc_result.stdout)["data"]
    # Section was created.
    assert any(s["anchor"] == "intro" for s in doc["sections"])
    # Phase was created with both tasks.
    phases = {p["slug"]: p for p in doc["phases"]}
    assert "ph1" in phases
    tasks = phases["ph1"]["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["text"] == "do x"
    assert tasks[1]["text"] == "do y"


# Task 2: task add (append) emits {rev, warnings, task:{phase, index}}
# with index = prior_len - 1 (0-based last position after append).
def test_task_add_append_emits_index(patched_cli: None) -> None:
    # _VALID_CREATE already has one task ("t1") in phase "a".
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


# Task 2: task add --at N emits index = N.
def test_task_add_at_emits_index(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "add", "demo", "p1", "a", "inserted", "--at", "0"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["task"]["phase"] == "a"
    assert parsed["task"]["index"] == 0
    assert "data" not in parsed


# Task 4: NO_COLOR=1 produces zero ANSI escape sequences.
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


# Task 5: index returned by `task add` addresses `set-checked` / `toggle`.
def test_task_add_index_is_addressable_by_set_checked(patched_cli: None) -> None:
    # _VALID_CREATE has one task in phase "a", so an append lands at index 1.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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
            "true",
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


# Task 5 (second add): index advances and the second task is also addressable.
def test_task_add_second_index_advances(patched_cli: None) -> None:
    # After two appends the indices are 1 and 2 respectively.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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
            "true",
            "--rev",
            second_add["rev"],
        ],
    )
    assert set_result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    tasks = doc["data"]["phases"][0]["tasks"]
    assert tasks[second_add["task"]["index"]]["checked"] is True
    assert tasks[first_add["task"]["index"]]["checked"] is False


# ---------------------------------------------------------------------------
# FIX 1: bad slug chars → structured validation error (exit 4), not 500/exit-1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_slug",
    [
        "nul\x00byte",  # NUL → server HTTP 500 without the fix
        "new\nline",  # newline → httpx.InvalidURL without the fix
        "frag#ment",  # '#' → permanently unaddressable slug
        "query?x",  # '?' → ditto
    ],
)
def test_bad_slug_chars_exit_validation_not_crash(
    patched_cli: None, bad_slug: str
) -> None:
    body = json.dumps({"type": "plan", "slug": bad_slug, "title": "T"})
    result = runner.invoke(cli.app, ["doc", "create", "demo", "--from-json", body])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# FIX 2: malformed --url → structured transport error, no traceback
# ---------------------------------------------------------------------------


def test_malformed_url_exits_transport_no_traceback() -> None:
    # A NUL byte in the URL triggers httpx.InvalidURL at Client construction (not
    # at request time). InvalidURL is NOT a RequestError subclass so it was
    # previously uncaught; FIX 2 adds an explicit catch mapping it to TRANSPORT.
    result = runner.invoke(
        cli.app, ["--url", "http://\x00host", "doc", "get", "demo", "p1"]
    )
    assert result.exit_code == ExitCode.TRANSPORT
    err = json.loads(result.stderr)
    assert err["error"] == "transport"
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# FIX 3: doc view / project view emit JSON with a "url" key
# ---------------------------------------------------------------------------


def test_doc_view_emits_json_with_url_key(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["doc", "view", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "url" in parsed
    assert "p1" in parsed["url"]


def test_project_view_emits_json_with_url_key(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["project", "view", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "url" in parsed
    assert "demo" in parsed["url"]


# ---------------------------------------------------------------------------
# FIX 4: bad project/uid path segments → structured validation error (exit 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_project",
    [
        "frag#ment",  # '#' truncates URL to a different route
        "query?x",  # '?' ditto
        "has space",  # space → '%20' or truncation depending on encoding
        "new\nline",  # newline → httpx.InvalidURL
        "nul\x00byte",  # NUL → server crash or filesystem fault
    ],
)
def test_bad_project_on_create_exits_validation(
    patched_cli: None, bad_project: str
) -> None:
    # A bad project arg is caught client-side before any request is made.
    body = json.dumps({"type": "plan", "slug": "p1", "title": "T"})
    result = runner.invoke(cli.app, ["doc", "create", bad_project, "--from-json", body])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


def test_bad_project_on_list_exits_validation(patched_cli: None) -> None:
    # doc list with a bad project → exit 4, not a null/false result.
    result = runner.invoke(cli.app, ["doc", "list", "a#b"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


def test_bad_project_on_search_exits_validation(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["search", "a#b", "some query"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


def test_bad_uid_exits_validation(patched_cli: None) -> None:
    # A bad --uid on any command → exit 4 structured error.
    result = runner.invoke(cli.app, ["--uid", "x#y", "doc", "list", "demo"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


def test_bad_project_nothing_stored(patched_cli: None) -> None:
    # A bad project arg is rejected before any write; a subsequent list must not
    # show the document.
    body = json.dumps({"type": "plan", "slug": "p-check", "title": "T"})
    create_result = runner.invoke(
        cli.app, ["doc", "create", "a#b", "--from-json", body]
    )
    assert create_result.exit_code == ExitCode.VALIDATION

    # Nothing was stored — listing the valid project "demo" won't show it either.
    list_result = runner.invoke(cli.app, ["doc", "list", "demo"])
    assert list_result.exit_code == 0
    listed = json.loads(list_result.stdout)
    slugs = [d["slug"] for d in listed.get("docs", [])]
    assert "p-check" not in slugs


def test_valid_segments_still_work(patched_cli: None) -> None:
    # Legitimate project/uid/slug values must not be rejected by _seg.
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", _VALID_CREATE]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["slug"] == "p1"


# ---------------------------------------------------------------------------
# Feature: project set-name / display-name registry
# ---------------------------------------------------------------------------


def test_project_set_name_round_trips(patched_cli: None) -> None:
    # set-name exits 0 and returns {project, name}.
    result = runner.invoke(
        cli.app, ["project", "set-name", "demo", "My Project (2026)"]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["project"] == "demo"
    assert parsed["name"] == "My Project (2026)"


def test_project_list_reports_name_after_set(patched_cli: None) -> None:
    # Create a doc so the project exists, then name it and verify list carries name.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(cli.app, ["project", "set-name", "demo", "Demo Project"])
    result = runner.invoke(cli.app, ["project", "list"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    items = parsed["data"]["items"]
    demo = next((i for i in items if i["project"] == "demo"), None)
    assert demo is not None
    assert demo["name"] == "Demo Project"


def test_project_list_name_is_none_when_unset(patched_cli: None) -> None:
    # A project with no display name set should return name=null in the listing.
    # Use a unique project slug that has never been named in this fixture scope.
    unnamed_body = json.dumps({"type": "plan", "slug": "u1", "title": "Unnamed"})
    runner.invoke(
        cli.app,
        ["doc", "create", "unnamed-proj", "--from-json", "-"],
        input=unnamed_body,
    )
    result = runner.invoke(cli.app, ["project", "list"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    items = parsed["data"]["items"]
    proj = next((i for i in items if i["project"] == "unnamed-proj"), None)
    assert proj is not None
    assert proj["name"] is None


def test_project_set_name_empty_exits_validation(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["project", "set-name", "demo", "   "])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"


def test_project_set_name_foreign_uid_exits_forbidden(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app, ["--uid", "evil", "project", "set-name", "demo", "Name"]
    )
    assert result.exit_code == ExitCode.FORBIDDEN


def test_phase_set_prose_flags_persist(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


def test_section_add_placement_flag_persists(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["section", "add", "demo", "p1", "ctx", "Context", "--placement", "trail"],
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    section = json.loads(get_result.stdout)["data"]["sections"][0]
    assert section["placement"] == "trail"


def test_phase_set_help_lists_prose_options(patched_cli: None) -> None:
    import re

    # Force a wide terminal so Typer doesn't truncate option names with an ellipsis
    # (the default 80-col render is width-fragile).
    result = runner.invoke(cli.app, ["phase", "set", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert "--intro" in plain
    assert "--exit-criteria" in plain
    assert "--notes" in plain


def test_section_add_help_lists_placement_choices(patched_cli: None) -> None:
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


def test_section_add_invalid_placement_exits_usage(patched_cli: None) -> None:
    # A bad enum CHOICE is a Typer parse-time usage error (exit 2), distinct from a
    # parseable-but-invalid value that reaches the server as a 422 (exit 4).
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["section", "add", "demo", "p1", "ctx", "Context", "--placement", "sideways"],
    )
    assert result.exit_code == ExitCode.USAGE


def test_phase_set_intro_empty_string_clears(patched_cli: None) -> None:
    # '' is sent (not omitted), so it clears a previously-set field — the CLI-layer
    # invariant the help advertises and that exclude_none must preserve.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(cli.app, ["phase", "set", "demo", "p1", "a", "--intro", "seeded"])
    result = runner.invoke(cli.app, ["phase", "set", "demo", "p1", "a", "--intro", ""])
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert json.loads(get_result.stdout)["data"]["phases"][0]["intro"] == ""


def test_section_set_placement_flag_persists(patched_cli: None) -> None:
    # The set path (vs add) drives --placement through runner.invoke end to end.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    runner.invoke(cli.app, ["section", "add", "demo", "p1", "ctx", "Context"])
    result = runner.invoke(
        cli.app, ["section", "set", "demo", "p1", "ctx", "--placement", "trail"]
    )
    assert result.exit_code == 0
    get_result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert json.loads(get_result.stdout)["data"]["sections"][0]["placement"] == "trail"


# ---------------------------------------------------------------------------
# Feature: phase set --<field>-file variants
# ---------------------------------------------------------------------------


def test_phase_set_intro_file_reads_from_file(
    patched_cli: None, tmp_path: Path
) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


def test_phase_set_notes_file_stdin(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
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


def test_phase_set_inline_and_file_conflict_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "set", "demo", "p1", "a", "--intro", "x", "--intro-file", "/tmp/x"],
    )
    assert result.exit_code == ExitCode.VALIDATION


def test_phase_set_missing_file_exits_validation(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=_VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["phase", "set", "demo", "p1", "a", "--notes-file", "/nonexistent/nope.md"],
    )
    assert result.exit_code == ExitCode.VALIDATION
