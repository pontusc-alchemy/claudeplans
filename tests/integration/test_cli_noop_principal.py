"""The CLI's resolved uid meeting the server's configured principal."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from _cli import runner

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_cli import cli
from claudeplans_cli.client import PlanClient
from claudeplans_contracts import ExitCode
from conftest import SyncASGITransport, plan_client

PRINCIPAL = "alek"


@pytest.fixture
def cli_against_alek_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Patch the CLI onto a server whose noop principal is PRINCIPAL, not "dev"."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            noop_uid=PRINCIPAL,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )
    transport = SyncASGITransport(app)
    client: PlanClient = plan_client(transport)
    monkeypatch.setattr(cli, "build_client", lambda _url: client)
    try:
        yield
    finally:
        transport.close()


@pytest.mark.usefixtures("cli_against_alek_server")
def test_matching_uid_may_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the feature: uid resolves to the principal, so writes land.

    This is the seam a uid-deriving CLI plugs into — derived or explicit, the write
    succeeds exactly when the resolved uid equals the server's principal.
    """
    monkeypatch.setenv("CLAUDEPLANS_UID", PRINCIPAL)
    result = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--type", "plan", "--slug", "p1", "--title", "P"],
    )
    assert result.exit_code == ExitCode.OK


@pytest.mark.usefixtures("cli_against_alek_server")
def test_default_dev_uid_is_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a matching uid the CLI falls back to "dev" and the server refuses it."""
    monkeypatch.delenv("CLAUDEPLANS_UID", raising=False)
    result = runner.invoke(
        cli.app,
        ["doc", "create", "demo", "--type", "plan", "--slug", "p1", "--title", "P"],
    )
    assert result.exit_code == ExitCode.FORBIDDEN
