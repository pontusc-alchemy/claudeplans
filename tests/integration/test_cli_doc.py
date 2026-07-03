"""CLI end-to-end tests for the `doc` command group."""

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from _cli import VALID_CREATE, assert_validation_exit, runner

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_cli import cli
from claudeplans_contracts import ExitCode


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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_VALID_RESEARCH = json.dumps({"type": "research", "slug": "r1", "title": "R One"})

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


@pytest.mark.usefixtures("patched_cli")
def test_create_from_stdin_exits_ok_and_prints_slug() -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["slug"] == "p1"
    assert "rev" in parsed
    assert "data" not in parsed


@pytest.mark.usefixtures("patched_cli")
def test_doc_create_shell_flags_set_status_description_date() -> None:
    # The shell create form lands status/description/date in ONE call (no follow-up
    # doc set / set-status).
    result = runner.invoke(
        cli.app,
        [
            "doc",
            "create",
            "demo",
            "--type",
            "plan",
            "--slug",
            "sc",
            "--title",
            "SC",
            "--status",
            "active",
            "--description",
            "a desc",
            "--date",
            "2026-06-26",
        ],
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "sc"]).stdout)
    data = doc["data"]
    assert data["status"] == "active"
    assert data["description"] == "a desc"
    assert data["date"] == "2026-06-26"


@pytest.mark.usefixtures("patched_cli")
def test_doc_create_shell_status_omitted_defaults_draft() -> None:
    # Omitting --status falls back to the DTO's draft default (status is only added
    # to the create body when explicitly given).
    result = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--type", "plan", "--slug", "sc2", "--title", "SC2"],
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "sc2"]).stdout)
    assert doc["data"]["status"] == "draft"


@pytest.mark.usefixtures("patched_cli")
def test_get_missing_doc_exits_not_found() -> None:
    result = runner.invoke(cli.app, ["doc", "get", "demo", "ghost"])
    assert result.exit_code == ExitCode.NOT_FOUND
    err = json.loads(result.stderr)
    assert err["error"] == "not_found"


@pytest.mark.usefixtures("patched_cli")
def test_malformed_from_json_exits_validation() -> None:
    result = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", '{"type":"plan"}'],
    )
    assert result.exit_code == 4


@pytest.mark.usefixtures("patched_cli")
def test_foreign_uid_write_exits_forbidden() -> None:
    # Under noop auth the caller is always "dev"; a write to a foreign path-uid is
    # Forbidden (403 fires before the not-found read) -> exit 3.
    result = runner.invoke(
        cli.app, ["--uid", "evil", "doc", "status", "demo", "ghost", "active"]
    )
    assert result.exit_code == 3


@pytest.mark.usefixtures("patched_cli")
def test_create_full_flag_prints_full_doc() -> None:
    result = runner.invoke(
        cli.app,
        ["--full", "doc", "create", "demo", "--from-json", "-"],
        input=VALID_CREATE,
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["slug"] == "p1"
    assert "rev" in parsed


@pytest.mark.usefixtures("patched_cli")
def test_create_empty_title_exits_validation() -> None:
    # DocumentCreate has no title validator; the server's Document compose rejects it.
    body = json.dumps({"type": "plan", "slug": "p2", "title": ""})
    result = runner.invoke(cli.app, ["doc", "create", "demo", "--from-json", body])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_title_and_description() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["doc", "set", "demo", "p1", "--title", "New Title", "--description", "Desc"],
    )
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["title"] == "New Title"
    assert doc["data"]["description"] == "Desc"


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_title_only_leaves_description() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
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


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_frontmatter_invalid_json_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "set", "demo", "p1", "--frontmatter", "{bad"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_clear_description_nulls_it() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--description", "D1"])
    result = runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--clear-description"])
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["description"] is None


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_description_and_clear_description_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        [
            "doc",
            "set",
            "demo",
            "p1",
            "--description",
            "D1",
            "--clear-description",
        ],
    )
    assert_validation_exit(result)
    err = json.loads(result.stderr)
    assert "mutually exclusive" in err["detail"]


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_clear_date_nulls_it() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--date", "2024-01-01"])
    result = runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--clear-date"])
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["date"] is None


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_date_and_clear_date_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app,
        ["doc", "set", "demo", "p1", "--date", "2024-01-01", "--clear-date"],
    )
    assert_validation_exit(result)
    err = json.loads(result.stderr)
    assert "mutually exclusive" in err["detail"]


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_empty_title_exits_validation() -> None:
    # `doc set --title ""` must reject via the phase-2 validator (re-validation on
    # persist), not silently blank the title.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "set", "demo", "p1", "--title", ""])
    assert_validation_exit(result)


def test_search_finds_doc_by_title(live_url: str) -> None:
    # Create a doc via HTTP, then poll the search index (async refresh) before
    # driving the CLI against the same live server.
    import time

    base = live_url
    with httpx.Client(base_url=base) as http:
        http.post(
            "/v1/users/dev/projects/demo/docs",
            json=json.loads(VALID_CREATE),
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
            json=json.loads(VALID_CREATE),
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
    # VALID_CREATE has phase name "Alpha"; searching for it should surface a hit
    # with kind == "phase", exercising the section/phase index branch.
    import time

    base = live_url
    with httpx.Client(base_url=base) as http:
        http.post(
            "/v1/users/dev/projects/demo/docs",
            json=json.loads(VALID_CREATE),
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


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_returns_non_empty_rev() -> None:
    # Default output is the bare rev token (no JSON envelope), so it composes
    # directly as --rev "$(claudeplans doc rev ...)".
    create_result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    create_rev = json.loads(create_result.stdout)["rev"]
    result = runner.invoke(cli.app, ["doc", "rev", "demo", "p1"])
    assert result.exit_code == 0
    token = result.stdout.strip()
    assert token  # non-empty
    assert token.isdigit()
    assert "{" not in token
    assert token == create_rev


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_json_flag_emits_envelope() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "rev", "demo", "p1", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["rev"].isdigit()


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_full_flag_emits_envelope() -> None:
    # The global --full flag is passed BEFORE the subcommand.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["--full", "doc", "rev", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["rev"].isdigit()


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_json_and_full_flags_together_emit_one_envelope() -> None:
    # --json and global --full both request the envelope; combined they still
    # print exactly one {rev} envelope, not a conflict/duplication.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["--full", "doc", "rev", "demo", "p1", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["rev"].isdigit()


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_bare_token_composes_as_rev() -> None:
    # The ergonomic win this phase exists for: no jq/json.loads needed to extract
    # the rev before using it in a position-sensitive write.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev_token = runner.invoke(cli.app, ["doc", "rev", "demo", "p1"]).stdout.strip()
    result = runner.invoke(
        cli.app,
        ["task", "toggle", "demo", "p1", "a", "0", "--rev", rev_token],
    )
    assert result.exit_code == 0


@pytest.mark.usefixtures("patched_cli")
def test_doc_rev_missing_doc_exits_not_found() -> None:
    result = runner.invoke(cli.app, ["doc", "rev", "demo", "ghost"])
    assert result.exit_code == ExitCode.NOT_FOUND
    err = json.loads(result.stderr)
    assert err["error"] == "not_found"


@pytest.mark.usefixtures("patched_cli")
def test_doc_list_type_filter_research_only() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
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


@pytest.mark.usefixtures("patched_cli")
def test_doc_list_type_filter_plan_only() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
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


@pytest.mark.usefixtures("patched_cli")
def test_create_reply_includes_type() -> None:
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed.get("type") == "plan"


@pytest.mark.usefixtures("patched_cli")
def test_doc_delete_emits_rev_warnings() -> None:
    create_result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    rev = json.loads(create_result.stdout)["rev"]
    result = runner.invoke(cli.app, ["doc", "delete", "demo", "p1", "--rev", rev])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "warnings" in parsed
    assert "deleted" not in parsed


@pytest.mark.usefixtures("patched_cli")
def test_doc_list_emits_data_warnings_envelope() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "list", "demo"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "data" in parsed
    assert "warnings" in parsed
    assert isinstance(parsed["warnings"], list)


@pytest.mark.usefixtures("patched_cli")
def test_doc_phases_includes_warnings() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "phases", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "phases" in parsed
    assert "warnings" in parsed
    assert isinstance(parsed["warnings"], list)


@pytest.mark.usefixtures("patched_cli")
def test_doc_get_unknown_field_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--fields", "no_such_field"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_get_absent_section_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--section", "no_such_anchor"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_get_absent_phase_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["doc", "get", "demo", "p1", "--phase", "no_such_phase"]
    )
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_set_status_alias_works() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "set-status", "demo", "p1", "active"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "rev" in parsed
    assert "warnings" in parsed
    # Verify the status actually changed.
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["status"] == "active"


@pytest.mark.usefixtures("patched_cli")
def test_doc_status_archived_round_trips() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "status", "demo", "p1", "archived"])
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["status"] == "archived"
    # Unarchive is just setting the status back.
    result = runner.invoke(cli.app, ["doc", "status", "demo", "p1", "active"])
    assert result.exit_code == 0
    doc = json.loads(runner.invoke(cli.app, ["doc", "get", "demo", "p1"]).stdout)
    assert doc["data"]["status"] == "active"


@pytest.mark.usefixtures("patched_cli")
def test_doc_link_nonexistent_ref_exits_validation() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(cli.app, ["doc", "link", "demo", "p1", "ghost_ref"])
    assert_validation_exit(result)


@pytest.mark.usefixtures("patched_cli")
def test_doc_link_real_research_ref_succeeds() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--from-json", "-"],
        input=_VALID_RESEARCH,
    )
    result = runner.invoke(cli.app, ["doc", "link", "demo", "p1", "r1"])
    assert result.exit_code == 0


@pytest.mark.usefixtures("patched_cli")
def test_create_from_json_full_scaffold() -> None:
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


@pytest.mark.usefixtures("patched_cli")
def test_doc_view_emits_json_with_url_key() -> None:
    result = runner.invoke(cli.app, ["doc", "view", "demo", "p1"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "url" in parsed
    assert "p1" in parsed["url"]


@pytest.mark.usefixtures("patched_cli")
def test_doc_create_date_rejects_control_chars() -> None:
    # A newline embedded in --date must be rejected as a control character (exit 4).
    result = runner.invoke(
        cli.app,
        [
            "doc",
            "create",
            "demo",
            "--type",
            "plan",
            "--slug",
            "dd1",
            "--title",
            "T",
            "--date",
            "2026\nINJECT",
        ],
    )
    assert result.exit_code == ExitCode.VALIDATION


@pytest.mark.usefixtures("patched_cli")
def test_doc_create_date_rejects_non_iso() -> None:
    # A syntactically invalid date string must be rejected (exit 4).
    result = runner.invoke(
        cli.app,
        [
            "doc",
            "create",
            "demo",
            "--type",
            "plan",
            "--slug",
            "dd2",
            "--title",
            "T",
            "--date",
            "not-a-date",
        ],
    )
    assert result.exit_code == ExitCode.VALIDATION
