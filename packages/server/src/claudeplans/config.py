"""Runtime configuration — a dependency-free leaf loaded from the environment.

pydantic-settings BaseSettings; nested per-backend so each backend carries only
its own settings. The default auth mode is the cloud one (iap), not the dev
no-op: defaults must be safe. fail_closed_check enforces the unsafe-combination
rule and is invoked from main.py at startup, before any request is served.
"""

from enum import StrEnum

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageBackend(StrEnum):
    filesystem = "filesystem"
    gcs = "gcs"  # deferred to the cloud migration


class AuthMode(StrEnum):
    noop = "noop"  # dev/local only: a single fixed trusted user
    iap = "iap"  # deferred to the cloud migration


class FilesystemSettings(BaseModel):
    """Filesystem backend settings (the default, local-first backend)."""

    root: str = "./data"


class Settings(BaseSettings):
    """Top-level settings. Env vars are prefixed CLAUDEPLANS_, nested with `__`.

    e.g. CLAUDEPLANS_STORAGE_BACKEND=filesystem,
         CLAUDEPLANS_FILESYSTEM__ROOT=/var/lib/claudeplans
    """

    model_config = SettingsConfigDict(
        env_prefix="CLAUDEPLANS_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    storage_backend: StorageBackend = StorageBackend.filesystem
    auth_mode: AuthMode = AuthMode.iap  # fail-closed default
    filesystem: FilesystemSettings = FilesystemSettings()


def load_settings() -> Settings:
    """Build Settings from the environment.

    Raises pydantic ValidationError on bad input.
    """
    return Settings()


def fail_closed_check(settings: Settings) -> None:
    """Refuse to start in an unsafe combination.

    The dev no-op provider trusts a single fixed user, so it must never run in
    front of a cloud backend. The seam grows as more backends land.
    """
    if (
        settings.auth_mode is AuthMode.noop
        and settings.storage_backend is StorageBackend.gcs
    ):
        raise RuntimeError(
            "fail-closed: AUTH_MODE=noop with STORAGE_BACKEND=gcs is forbidden "
            "(no-op auth must not front a cloud backend)"
        )
