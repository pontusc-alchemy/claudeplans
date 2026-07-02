"""Tests for config round-trip, resolution precedence, list commands, and view URLs.

Uses the same in-process harness as the other CLI tests (the `patched_cli`
fixture in conftest.py): `build_client` is monkeypatched so CliRunner drives
the full router stack without a socket.

All tests are hermetic: XDG_CONFIG_HOME is redirected to a per-test tmp dir so the
real ~/.config/claudeplans/config.toml is never read or written.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient
from claudeplans_cli.config import read_config

runner = CliRunner()

_PLAN_BODY = json.dumps(
    {
        "type": "plan",
        "slug": "p1",
        "title": "Plan One",
        "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
    }
)

_RESEARCH_BODY = json.dumps(
    {
        "type": "research",
        "slug": "r1",
        "title": "Research One",
    }
)


@pytest.fixture(autouse=True)
def isolate_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect XDG_CONFIG_HOME to a fresh tmp dir for every test in this module."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def patched_cli(client: PlanClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Monkeypatch build_client so CLI commands hit the in-process ASGI app."""

    def _build(url: str) -> PlanClient:
        return client

    monkeypatch.setattr(cli, "build_client", _build)
    # Ensure no stray env vars from the outer shell bleed in.
    monkeypatch.delenv("CLAUDEPLANS_URL", raising=False)
    monkeypatch.delenv("CLAUDEPLANS_UID", raising=False)
    yield


# ---------------------------------------------------------------------------
# config round-trip
# ---------------------------------------------------------------------------


def test_config_set_writes_file(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["config", "set", "--url", "http://x:9", "--uid", "alice"]
    )
    assert result.exit_code == 0
    cfg = read_config()
    assert cfg["url"] == "http://x:9"
    assert cfg["uid"] == "alice"


def test_config_set_merge_preserves_existing_url(tmp_path: Path) -> None:
    runner.invoke(cli.app, ["config", "set", "--url", "http://x:9", "--uid", "alice"])
    result = runner.invoke(cli.app, ["config", "set", "--uid", "bob"])
    assert result.exit_code == 0
    cfg = read_config()
    assert cfg["url"] == "http://x:9"  # preserved
    assert cfg["uid"] == "bob"  # updated


def test_config_set_no_args_exits_nonzero() -> None:
    result = runner.invoke(cli.app, ["config", "set"])
    assert result.exit_code != 0


def test_config_show_reflects_written_values(tmp_path: Path) -> None:
    runner.invoke(
        cli.app,
        ["config", "set", "--url", "http://myserver:8", "--uid", "carol"],
    )
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["url"] == "http://myserver:8"
    assert parsed["uid"] == "carol"
    assert "path" in parsed


# ---------------------------------------------------------------------------
# resolution precedence: flag > env > config > default
# ---------------------------------------------------------------------------


def test_config_show_default_when_no_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDEPLANS_URL", raising=False)
    monkeypatch.delenv("CLAUDEPLANS_UID", raising=False)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["url"] == "http://127.0.0.1:8000"
    assert parsed["uid"] == "dev"


def test_config_show_env_overrides_config_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner.invoke(
        cli.app,
        ["config", "set", "--url", "http://cfg:1", "--uid", "cfg-user"],
    )
    monkeypatch.setenv("CLAUDEPLANS_URL", "http://env:2")
    monkeypatch.setenv("CLAUDEPLANS_UID", "env-user")
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["url"] == "http://env:2"
    assert parsed["uid"] == "env-user"


# ---------------------------------------------------------------------------
# project list / doc list against the in-process app
# ---------------------------------------------------------------------------


def test_project_list_contains_created_projects(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "proj-a", "--from-json", "-"], input=_PLAN_BODY
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "proj-b", "--from-json", "-"],
        input=_RESEARCH_BODY,
    )
    result = runner.invoke(cli.app, ["project", "list"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    projects = {item["project"] for item in parsed["data"]["items"]}
    assert "proj-a" in projects
    assert "proj-b" in projects


def test_doc_list_contains_created_docs(patched_cli: None) -> None:
    runner.invoke(
        cli.app, ["doc", "create", "myproj", "--from-json", "-"], input=_PLAN_BODY
    )
    runner.invoke(
        cli.app,
        ["doc", "create", "myproj", "--from-json", "-"],
        input=_RESEARCH_BODY,
    )
    result = runner.invoke(cli.app, ["doc", "list", "myproj"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    slugs = {item["slug"] for item in parsed["data"]["items"]}
    assert "p1" in slugs
    assert "r1" in slugs


def test_doc_list_empty_project_returns_ok(patched_cli: None) -> None:
    result = runner.invoke(cli.app, ["doc", "list", "no-such-proj"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["data"]["items"] == []


# ---------------------------------------------------------------------------
# doc view / project view — URL construction, no network request
# ---------------------------------------------------------------------------


def test_doc_view_prints_correct_url(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--url",
            "http://myhost:9000",
            "--uid",
            "alice",
            "doc",
            "view",
            "myproj",
            "my-slug",
        ],
    )
    assert result.exit_code == 0
    import json

    parsed = json.loads(result.stdout)
    assert parsed["url"] == (
        "http://myhost:9000/v1/users/alice/projects/myproj/docs/my-slug/view"
    )


def test_project_view_prints_correct_url(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--url",
            "http://myhost:9000",
            "--uid",
            "alice",
            "project",
            "view",
            "myproj",
        ],
    )
    assert result.exit_code == 0
    import json

    parsed = json.loads(result.stdout)
    assert parsed["url"] == "http://myhost:9000/v1/users/alice/projects/myproj/"


# ---------------------------------------------------------------------------
# FIX 1 + 2 — config set: control-char and empty rejection
# ---------------------------------------------------------------------------


def test_config_set_rejects_newline_in_url() -> None:
    result = runner.invoke(cli.app, ["config", "set", "--url", "http://x\n.bad"])
    assert result.exit_code == 4


def test_config_set_rejects_newline_in_uid() -> None:
    result = runner.invoke(cli.app, ["config", "set", "--uid", "user\nid"])
    assert result.exit_code == 4


def test_config_set_rejects_empty_url() -> None:
    result = runner.invoke(cli.app, ["config", "set", "--url", ""])
    assert result.exit_code == 4


def test_config_set_rejects_empty_uid() -> None:
    result = runner.invoke(cli.app, ["config", "set", "--uid", ""])
    assert result.exit_code == 4


def test_config_set_backslash_and_quote_roundtrip(tmp_path: Path) -> None:
    """A value with a backslash and double-quote survives write → read."""
    value = 'http://x/path\\with"quotes'
    result = runner.invoke(cli.app, ["config", "set", "--url", value])
    assert result.exit_code == 0
    cfg = read_config()
    assert cfg["url"] == value


def test_config_set_survives_malformed_existing_config(tmp_path: Path) -> None:
    """config set succeeds even when the existing config.toml is garbage."""
    from claudeplans_cli.config import config_path

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("this is not [ valid ] = toml !!!!\n")
    result = runner.invoke(cli.app, ["config", "set", "--url", "http://recovered:1"])
    assert result.exit_code == 0
    cfg = read_config()
    assert cfg["url"] == "http://recovered:1"


# ---------------------------------------------------------------------------
# FIX 1 — resolution precedence: flag > env > config > default
# ---------------------------------------------------------------------------


def test_flag_beats_env_on_doc_view(
    patched_cli: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--url flag takes precedence over CLAUDEPLANS_URL env in view URL."""
    monkeypatch.setenv("CLAUDEPLANS_URL", "http://env-server:1")
    result = runner.invoke(
        cli.app,
        [
            "--url",
            "http://flag-server:2",
            "--uid",
            "alice",
            "doc",
            "view",
            "myproj",
            "my-slug",
        ],
    )
    assert result.exit_code == 0
    url = result.stdout.strip()
    assert "flag-server:2" in url
    assert "env-server" not in url


def test_config_beats_default_on_config_show(tmp_path: Path) -> None:
    """Config file value is reflected by config show when no env is set."""
    runner.invoke(
        cli.app, ["config", "set", "--url", "http://cfg-server:3", "--uid", "cfguser"]
    )
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["url"] == "http://cfg-server:3"
    assert parsed["uid"] == "cfguser"


# ---------------------------------------------------------------------------
# FIX 3 — trailing slash in base_url does not produce // in view URLs
# ---------------------------------------------------------------------------


def test_doc_view_trailing_slash_no_double_slash(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--url",
            "http://myhost:9000/",  # trailing slash
            "--uid",
            "alice",
            "doc",
            "view",
            "myproj",
            "my-slug",
        ],
    )
    assert result.exit_code == 0
    url = result.stdout.strip()
    assert "//" not in url.replace("http://", "")


def test_project_view_trailing_slash_no_double_slash(patched_cli: None) -> None:
    result = runner.invoke(
        cli.app,
        [
            "--url",
            "http://myhost:9000/",  # trailing slash
            "--uid",
            "alice",
            "project",
            "view",
            "myproj",
        ],
    )
    assert result.exit_code == 0
    url = result.stdout.strip()
    assert "//" not in url.replace("http://", "")


# ---------------------------------------------------------------------------
# FIX 5 — lone-surrogate / non-UTF-8 value rejected at validation (exit 4)
# ---------------------------------------------------------------------------


def test_config_set_rejects_lone_surrogate_in_url() -> None:
    """A lone surrogate in --url must exit 4 (ValidationError), no traceback.

    CliRunner records a clean typer.Exit as SystemExit; any other exception type
    means an unhandled error escaped handle_errors.
    """
    result = runner.invoke(cli.app, ["config", "set", "--url", "\udc80"])
    assert result.exit_code == 4
    # A clean exit surfaces as SystemExit, not UnicodeEncodeError or similar.
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_config_set_lone_surrogate_leaves_existing_config_intact(
    tmp_path: Path,
) -> None:
    """A failed config set (surrogate) must not truncate a pre-existing config."""
    # Write a good config first.
    ok = runner.invoke(
        cli.app, ["config", "set", "--url", "http://good", "--uid", "dev"]
    )
    assert ok.exit_code == 0

    # Now attempt a write with a lone surrogate — must fail at validation.
    bad = runner.invoke(cli.app, ["config", "set", "--url", "\udc80"])
    assert bad.exit_code == 4

    # The pre-existing config must be unchanged and fully readable.
    cfg = read_config()
    assert cfg["url"] == "http://good"
    assert cfg["uid"] == "dev"


# ---------------------------------------------------------------------------
# FIX 4 — invalid segment → 422 → exit 4 at the CLI
# ---------------------------------------------------------------------------


def test_get_json_422_maps_to_validation_error_exit_4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_json maps a server 422 response to ValidationError → exit 4.

    Injects a stub transport that always returns 422 so the full client error
    mapping is exercised without needing a real invalid URL segment.
    """
    import httpx

    from claudeplans_cli.client import PlanClient

    class _Always422(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": "invalid key segment"},
                request=request,
            )

    stub_client = PlanClient(
        http_client=httpx.Client(transport=_Always422(), base_url="http://test")
    )

    def _build(_url: str) -> PlanClient:
        return stub_client

    monkeypatch.setattr(cli, "build_client", _build)
    monkeypatch.delenv("CLAUDEPLANS_URL", raising=False)
    monkeypatch.delenv("CLAUDEPLANS_UID", raising=False)

    result = runner.invoke(cli.app, ["doc", "list", "any-project"])
    assert result.exit_code == 4

    result2 = runner.invoke(cli.app, ["project", "list"])
    assert result2.exit_code == 4
