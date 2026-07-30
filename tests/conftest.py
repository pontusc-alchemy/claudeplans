"""Suite-wide isolation from the ambient environment."""

import os

import pytest


@pytest.fixture(autouse=True)
def _scrub_claudeplans_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide every CLAUDEPLANS_ variable from the test run.

    Settings reads them all, so an exported CLAUDEPLANS_NOOP_UID would move the noop
    principal off "dev" and 403 the many tests that write to /v1/users/dev/....
    Tests that want a variable set it via monkeypatch, which restores it afterwards.
    """
    for name in [n for n in os.environ if n.startswith("CLAUDEPLANS_")]:
        monkeypatch.delenv(name)
