"""Config module tests: environment-driven Settings fields."""

import pytest

from claudeplans.config import Settings


def test_version_picked_up_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDEPLANS_VERSION", "9.9.9")
    assert Settings().version == "9.9.9"
