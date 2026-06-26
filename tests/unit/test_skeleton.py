"""Skeleton smoke tests: packages import, config is fail-closed, the app builds,
and the auth/error seams behave.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from claudeplans.auth.authz import can_write
from claudeplans.auth.provider import CurrentUser
from claudeplans.config import (
    AuthMode,
    FilesystemSettings,
    Settings,
    StorageBackend,
    fail_closed_check,
)
from claudeplans.main import create_app
from claudeplans_cli.cli import app as claudeplans_app
from claudeplans_contracts.errors import ExitCode, NotFound, StaleRevision


def test_app_builds() -> None:
    app = create_app(
        Settings(auth_mode=AuthMode.noop, storage_backend=StorageBackend.filesystem)
    )
    assert isinstance(app, FastAPI)
    assert app.title == "claudeplans"


def test_default_settings_are_fail_closed() -> None:
    # The default auth mode must be the safe (cloud) one, not the dev no-op.
    assert Settings().auth_mode is AuthMode.iap


def test_fail_closed_rejects_noop_with_cloud_backend() -> None:
    bad = Settings(auth_mode=AuthMode.noop, storage_backend=StorageBackend.gcs)
    with pytest.raises(RuntimeError):
        fail_closed_check(bad)


def test_fail_closed_rejects_registry_inside_storage_root(tmp_path: Path) -> None:
    bad = Settings(
        filesystem=FilesystemSettings(root=str(tmp_path / "data")),
        registry_path=str(tmp_path / "data" / "users.json"),
    )
    with pytest.raises(RuntimeError, match="REGISTRY_PATH"):
        fail_closed_check(bad)


def test_fail_closed_allows_registry_outside_storage_root(tmp_path: Path) -> None:
    ok = Settings(
        filesystem=FilesystemSettings(root=str(tmp_path / "data")),
        registry_path=str(tmp_path / "users.json"),
    )
    fail_closed_check(ok)  # must not raise


def test_fail_closed_rejects_project_registry_inside_storage_root(
    tmp_path: Path,
) -> None:
    bad = Settings(
        filesystem=FilesystemSettings(root=str(tmp_path / "data")),
        project_registry_path=str(tmp_path / "data" / "projects.json"),
    )
    with pytest.raises(RuntimeError, match="PROJECT_REGISTRY_PATH"):
        fail_closed_check(bad)


def test_fail_closed_allows_project_registry_outside_storage_root(
    tmp_path: Path,
) -> None:
    ok = Settings(
        filesystem=FilesystemSettings(root=str(tmp_path / "data")),
        project_registry_path=str(tmp_path / "projects.json"),
    )
    fail_closed_check(ok)  # must not raise


def test_can_write_is_write_own() -> None:
    user = CurrentUser(uid="u1", name="alice", namespace="alice")
    assert can_write(user, "alice") is True
    assert can_write(user, "bob") is False


def test_exit_codes_and_errors_present() -> None:
    assert ExitCode.OK == 0
    assert ExitCode.STALE_REV == 9
    assert issubclass(StaleRevision, Exception)
    assert issubclass(NotFound, Exception)


def test_claudeplans_cli_help_runs() -> None:
    # A command-less Typer app needs a callback to be invocable at all; this
    # guards against regressing to "Could not get a command for this Typer instance".
    result = CliRunner().invoke(claudeplans_app, ["--help"])
    assert result.exit_code == 0
    assert "Agent client" in result.output
