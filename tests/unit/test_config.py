"""Config module tests: environment-driven Settings fields."""

import pytest
from pydantic import ValidationError

from claudeplans.config import Settings


def test_version_picked_up_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDEPLANS_VERSION", "9.9.9")
    assert Settings().version == "9.9.9"


def test_noop_uid_defaults_to_dev() -> None:
    assert Settings().noop_uid == "dev"


def test_noop_uid_picked_up_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDEPLANS_NOOP_UID", "alek")
    assert Settings().noop_uid == "alek"


@pytest.mark.parametrize(
    "value",
    [
        "has/slash",
        "has.dot",
        "has space",
        "has#hash",
        "has?query",
        "..",
        "",
        "nul\x00byte",
        "new\nline",
    ],
)
def test_noop_uid_rejects_illegal_key_segment(value: str) -> None:
    """Constructed directly, not via the env: os.environ cannot carry a NUL byte.

    Routing every case through monkeypatch.setenv would make that one unrepresentable
    and quietly drop it from the matrix.
    """
    with pytest.raises(ValidationError, match="CLAUDEPLANS_NOOP_UID"):
        Settings(noop_uid=value)


def test_illegal_noop_uid_in_the_env_fails_at_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDEPLANS_NOOP_UID", "has/slash")
    with pytest.raises(ValidationError, match="CLAUDEPLANS_NOOP_UID"):
        Settings()
