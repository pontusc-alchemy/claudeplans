"""Integration tests for the listing endpoints (project list + doc list).

Listing reads directly from the repository (no async index needed), so these
run under ASGITransport — no live uvicorn server required.
"""

from pathlib import Path

import httpx
from httpx import ASGITransport

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app

RESEARCH_BODY: dict[str, object] = {
    "type": "research",
    "slug": "r1",
    "title": "Research One",
    "status": "draft",
}

PLAN_BODY: dict[str, object] = {
    "type": "plan",
    "slug": "p1",
    "title": "Plan One",
    "status": "active",
}

PLAN_BODY_2: dict[str, object] = {
    "type": "plan",
    "slug": "p2",
    "title": "Plan Two",
    "status": "done",
}


def _client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _docs_url(uid: str, project: str) -> str:
    return f"/v1/users/{uid}/projects/{project}/docs"


def _projects_url(uid: str) -> str:
    return f"/v1/users/{uid}/projects"


def _doc_list_url(uid: str, project: str) -> str:
    return f"/v1/users/{uid}/projects/{project}/docs"


async def test_project_list_counts_and_sorts(tmp_path: Path) -> None:
    """Two docs in projA + one in projB → ProjectList with correct counts, sorted."""
    async with _client(tmp_path) as client:
        # projA: 2 docs
        r = await client.post(_docs_url("dev", "projA"), json=RESEARCH_BODY)
        assert r.status_code == 201
        r = await client.post(_docs_url("dev", "projA"), json=PLAN_BODY)
        assert r.status_code == 201
        # projB: 1 doc
        r = await client.post(_docs_url("dev", "projB"), json=PLAN_BODY_2)
        assert r.status_code == 201

        resp = await client.get(_projects_url("dev"))
        assert resp.status_code == 200
        body = resp.json()
        items = body["items"]
        assert len(items) == 2
        # Sorted ascending by project name.
        assert items[0]["project"] == "projA"
        assert items[0]["docs"] == 2
        assert items[1]["project"] == "projB"
        assert items[1]["docs"] == 1


async def test_doc_list_returns_slugs_title_type_status_sorted(
    tmp_path: Path,
) -> None:
    """Doc list for projA returns r1 + p1 with correct fields, sorted by slug."""
    async with _client(tmp_path) as client:
        await client.post(_docs_url("dev", "projA"), json=RESEARCH_BODY)
        await client.post(_docs_url("dev", "projA"), json=PLAN_BODY)

        resp = await client.get(_doc_list_url("dev", "projA"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == "projA"
        items = body["items"]
        assert len(items) == 2
        # Sorted by slug: "p1" < "r1".
        assert items[0]["slug"] == "p1"
        assert items[0]["title"] == "Plan One"
        assert items[0]["type"] == "plan"
        assert items[0]["status"] == "active"
        assert items[1]["slug"] == "r1"
        assert items[1]["title"] == "Research One"
        assert items[1]["type"] == "research"
        assert items[1]["status"] == "draft"


async def test_empty_project_returns_200_empty_list(tmp_path: Path) -> None:
    """Unknown/empty project returns 200 with empty items, not 404."""
    async with _client(tmp_path) as client:
        resp = await client.get(_doc_list_url("dev", "no-such-project"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["project"] == "no-such-project"
        assert body["items"] == []


async def test_cross_uid_isolation(tmp_path: Path) -> None:
    """Docs created under 'dev' do not appear when listing projects for 'other'."""
    async with _client(tmp_path) as client:
        await client.post(_docs_url("dev", "projA"), json=RESEARCH_BODY)

        resp = await client.get(_projects_url("other"))
        assert resp.status_code == 200
        assert resp.json()["items"] == []


async def test_corrupt_doc_skipped_by_list_and_counts_agree(tmp_path: Path) -> None:
    """A doc with a bogus type/status is skipped by doc list AND not counted by
    project list — so the two endpoints agree on the count.
    """
    import json

    async with _client(tmp_path) as client:
        # Create one valid doc.
        r = await client.post(_docs_url("dev", "projA"), json=RESEARCH_BODY)
        assert r.status_code == 201

        # Plant a corrupt envelope directly on disk (bad type + bad status).
        corrupt_key = "dev/projA/bad-doc"
        corrupt_path = tmp_path / f"{corrupt_key}.json"
        corrupt_path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {
            "rev": "1",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "document": {
                "type": "not-a-valid-type",
                "slug": "bad-doc",
                "title": "Corrupt",
                "status": "not-a-valid-status",
            },
        }
        corrupt_path.write_text(json.dumps(envelope))

        # doc list must return 200 and only include the valid doc (not 500).
        doc_resp = await client.get(_doc_list_url("dev", "projA"))
        assert doc_resp.status_code == 200
        doc_items = doc_resp.json()["items"]
        slugs = {i["slug"] for i in doc_items}
        assert "r1" in slugs
        assert "bad-doc" not in slugs
        valid_count = len(doc_items)

        # project list must count only the valid doc — same as doc list.
        proj_resp = await client.get(_projects_url("dev"))
        assert proj_resp.status_code == 200
        proj_items = {i["project"]: i["docs"] for i in proj_resp.json()["items"]}
        assert proj_items.get("projA") == valid_count


async def test_research_and_plan_list_with_correct_type(tmp_path: Path) -> None:
    """A research doc and a plan doc both appear with the right type and status."""
    async with _client(tmp_path) as client:
        await client.post(_docs_url("dev", "mixed"), json=RESEARCH_BODY)
        await client.post(
            _docs_url("dev", "mixed"),
            json={**PLAN_BODY, "status": "done"},
        )

        resp = await client.get(_doc_list_url("dev", "mixed"))
        assert resp.status_code == 200
        items = {i["slug"]: i for i in resp.json()["items"]}
        assert items["r1"]["type"] == "research"
        assert items["r1"]["status"] == "draft"
        assert items["p1"]["type"] == "plan"
        assert items["p1"]["status"] == "done"
