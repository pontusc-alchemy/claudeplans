"""Runtime configuration — a dependency-free leaf loaded from the environment.

pydantic-settings BaseSettings; nested per-backend so each backend carries only
its own settings. The default auth mode is the cloud one (iap), not the dev
no-op: defaults must be safe. fail_closed_check enforces the unsafe-combination
rule and is invoked from main.py at startup, before any request is served.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field
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
    # User registry path (CLAUDEPLANS_REGISTRY_PATH). MUST sit OUTSIDE filesystem.root,
    # or FilesystemRepository's rglob("*.json") walk would sweep it up as a stray key.
    registry_path: str = "./users.json"
    # 1 MiB cap on request bodies (CLAUDEPLANS_MAX_BODY_BYTES); must be positive.
    max_body_bytes: int = Field(default=1_048_576, gt=0)


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
            "fail-closed: CLAUDEPLANS_AUTH_MODE=noop with "
            "CLAUDEPLANS_STORAGE_BACKEND=gcs is forbidden "
            "(no-op auth must not front a cloud backend)"
        )
    if settings.storage_backend is StorageBackend.filesystem:
        root = Path(settings.filesystem.root).resolve()
        registry = Path(settings.registry_path).resolve()
        if registry == root or root in registry.parents:
            raise RuntimeError(
                "fail-closed: CLAUDEPLANS_REGISTRY_PATH must sit OUTSIDE "
                "CLAUDEPLANS_FILESYSTEM__ROOT (else the repository's *.json walk "
                "would sweep the registry file as a stray document)"
            )
