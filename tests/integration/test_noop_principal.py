"""The configurable noop principal, end to end over the app."""

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app

DOC = {"type": "plan", "slug": "p1", "title": "Plan One"}


def _client(tmp_path: Path, noop_uid: str) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            noop_uid=noop_uid,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_configured_principal_writes_its_own_namespace(tmp_path: Path) -> None:
    async with _client(tmp_path, "alek") as client:
        resp = await client.post("/v1/users/alek/projects/demo/docs", json=DOC)
        assert resp.status_code == 201


async def test_configured_principal_cannot_write_dev(tmp_path: Path) -> None:
    """Moving the principal must not widen it: write-own still holds the other way.

    The regressions worth catching are a principal that writes everywhere, and one
    still nailed to "dev" despite the config.
    """
    async with _client(tmp_path, "alek") as client:
        resp = await client.post("/v1/users/dev/projects/demo/docs", json=DOC)
        assert resp.status_code == 403


async def test_default_principal_still_owns_dev(tmp_path: Path) -> None:
    async with _client(tmp_path, "dev") as client:
        allowed = await client.post("/v1/users/dev/projects/demo/docs", json=DOC)
        denied = await client.post("/v1/users/alek/projects/demo/docs", json=DOC)
    assert (allowed.status_code, denied.status_code) == (201, 403)


async def test_reads_stay_open_across_namespaces(tmp_path: Path) -> None:
    async with _client(tmp_path, "alek") as client:
        await client.post("/v1/users/alek/projects/demo/docs", json=DOC)
        resp = await client.get("/v1/users/alek/projects/demo/docs/p1")
        assert resp.status_code == 200


@pytest.mark.parametrize("uid", ["alek", "dev", "some-one_2"])
async def test_principal_owns_whatever_uid_it_is_given(
    tmp_path: Path, uid: str
) -> None:
    async with _client(tmp_path, uid) as client:
        resp = await client.post(f"/v1/users/{uid}/projects/demo/docs", json=DOC)
        assert resp.status_code == 201
