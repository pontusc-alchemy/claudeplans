"""CLI end-to-end tests for the `errors` command group."""

import json
from pathlib import Path

import httpx
import pytest
from _cli import VALID_CREATE, runner

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient
from claudeplans_contracts import ExitCode


@pytest.mark.usefixtures("patched_cli")
def test_usage_error_exits_two_distinct_from_not_found() -> None:
    # A malformed command line (missing the required slug arg) is Typer/Click usage
    # -> exit 2, which NOT_FOUND (5) no longer collides with.
    result = runner.invoke(cli.app, ["doc", "get", "demo"])
    assert result.exit_code == ExitCode.USAGE
    assert result.exit_code != ExitCode.NOT_FOUND


def test_service_down_exits_transport_no_traceback(
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(cli, "build_client", lambda _url: down_client)
    result = runner.invoke(cli.app, ["doc", "get", "demo", "p1"])
    assert result.exit_code == ExitCode.TRANSPORT
    err = json.loads(result.stderr)
    assert err["error"] == "transport"
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("patched_cli")
def test_malformed_rev_exits_validation_with_invalid_rev_kind() -> None:
    # A malformed --rev is a client input error (exit 4), distinct from a genuine
    # concurrency conflict (exit 9) — it fails before any StaleRevision check.
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "toggle", "demo", "p1", "a", "0", "--rev", "abc"]
    )
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "invalid_rev"


@pytest.mark.usefixtures("patched_cli")
def test_empty_rev_exits_validation_with_invalid_rev_kind() -> None:
    runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", "-"], input=VALID_CREATE
    )
    result = runner.invoke(
        cli.app, ["task", "toggle", "demo", "p1", "a", "0", "--rev", ""]
    )
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "invalid_rev"


async def test_server_if_match_validation_400_vs_409(tmp_path: Path) -> None:
    # Direct-ASGI check of deps.py's require_if_match validation: the CLI's
    # client-side preflight fires before any HTTP call, so this exercises the
    # server-side validate_rev call inside the dependency itself. A malformed
    # If-Match is 400 (InvalidRev), never carrying current_rev/ETag; a
    # well-formed-but-wrong numeric If-Match is still 409 (StaleRevision) with
    # current_rev/ETag — proving FastAPI's exception handlers catch an error
    # raised inside a Depends().
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        create_resp = await async_client.post(
            "/v1/users/dev/projects/demo/docs", json=json.loads(VALID_CREATE)
        )
        assert create_resp.status_code == 201
        toggle_url = "/v1/users/dev/projects/demo/docs/p1/phases/a/tasks/0/toggle"

        bad_resp = await async_client.put(
            toggle_url, json={"checked": True}, headers={"If-Match": "abc"}
        )
        assert bad_resp.status_code == 400
        bad_body = bad_resp.json()
        assert "current_rev" not in bad_body
        assert bad_body["error"] == "invalid_rev"

        stale_resp = await async_client.put(
            toggle_url, json={"checked": True}, headers={"If-Match": "999999999"}
        )
        assert stale_resp.status_code == 409
        body = stale_resp.json()
        assert "current_rev" in body
        assert stale_resp.headers.get("ETag") == body["current_rev"]


async def test_server_optional_if_match_rejects_malformed_rev(tmp_path: Path) -> None:
    # require_optional_if_match's validate_rev branch is unreachable through the
    # CLI (client-side preflight fires first), so it needs this direct-ASGI case:
    # PUT .../tasks/checked (the OptionalIfMatchDep route) with a malformed
    # If-Match must still 400 with the invalid_rev discriminator.
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        create_resp = await async_client.post(
            "/v1/users/dev/projects/demo/docs", json=json.loads(VALID_CREATE)
        )
        assert create_resp.status_code == 201
        resp = await async_client.put(
            "/v1/users/dev/projects/demo/docs/p1/phases/a/tasks/checked",
            json={"checked": True},
            headers={"If-Match": "abc"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_rev"


@pytest.mark.parametrize(
    "bad_slug",
    [
        "nul\x00byte",  # NUL → server HTTP 500 without the fix
        "new\nline",  # newline → httpx.InvalidURL without the fix
        "frag#ment",  # '#' → permanently unaddressable slug
        "query?x",  # '?' → ditto
    ],
)
@pytest.mark.usefixtures("patched_cli")
def test_bad_slug_chars_exit_validation_not_crash(bad_slug: str) -> None:
    body = json.dumps({"type": "plan", "slug": bad_slug, "title": "T"})
    result = runner.invoke(cli.app, ["doc", "create", "demo", "--from-json", body])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


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
@pytest.mark.usefixtures("patched_cli")
def test_bad_project_on_create_exits_validation(bad_project: str) -> None:
    # A bad project arg is caught client-side before any request is made.
    body = json.dumps({"type": "plan", "slug": "p1", "title": "T"})
    result = runner.invoke(cli.app, ["doc", "create", bad_project, "--from-json", body])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("patched_cli")
def test_bad_project_on_list_exits_validation() -> None:
    # doc list with a bad project → exit 4, not a null/false result.
    result = runner.invoke(cli.app, ["doc", "list", "a#b"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("patched_cli")
def test_bad_project_on_search_exits_validation() -> None:
    result = runner.invoke(cli.app, ["search", "a#b", "some query"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("patched_cli")
def test_bad_uid_exits_validation() -> None:
    # A bad --uid on any command → exit 4 structured error.
    result = runner.invoke(cli.app, ["--uid", "x#y", "doc", "list", "demo"])
    assert result.exit_code == ExitCode.VALIDATION
    err = json.loads(result.stderr)
    assert err["error"] == "validation"
    assert "Traceback" not in result.stderr


@pytest.mark.usefixtures("patched_cli")
def test_bad_project_nothing_stored() -> None:
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


@pytest.mark.usefixtures("patched_cli")
def test_valid_segments_still_work() -> None:
    # Legitimate project/uid/slug values must not be rejected by _seg.
    result = runner.invoke(
        cli.app, ["doc", "create", "demo", "--from-json", VALID_CREATE]
    )
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["slug"] == "p1"
