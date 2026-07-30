"""Identity providers and the AUTH_MODE -> provider selection."""

import pytest

from claudeplans.auth.provider import DEV_USER, IapProvider, NoopProvider
from claudeplans.config import AuthMode, Settings
from claudeplans.main import select_provider


def test_dev_user_namespace_equals_uid() -> None:
    assert DEV_USER.namespace == DEV_USER.uid == "dev"


async def test_noop_provider_returns_dev_user() -> None:
    assert await NoopProvider()({}) == DEV_USER


async def test_noop_provider_honors_configured_uid() -> None:
    user = await NoopProvider("alek")({})
    assert user.uid == user.name == user.namespace == "alek"


def test_select_provider_noop() -> None:
    settings = Settings(auth_mode=AuthMode.noop)
    assert isinstance(select_provider(settings), NoopProvider)


async def test_select_provider_passes_noop_uid_through() -> None:
    provider = select_provider(Settings(auth_mode=AuthMode.noop, noop_uid="alek"))
    assert (await provider({})).namespace == "alek"


def test_select_provider_iap() -> None:
    settings = Settings(auth_mode=AuthMode.iap)
    assert isinstance(select_provider(settings), IapProvider)


async def test_iap_provider_is_deferred() -> None:
    with pytest.raises(NotImplementedError):
        await IapProvider()({})
