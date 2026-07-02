"""Integration test: the search endpoint over a live server, end-to-end freshness.

Search needs the lifespan — the index's background consumer builds from storage and
keeps fresh off the events feed — so these run on a real loopback uvicorn server (like
the SSE tests) rather than under ASGITransport, which never enters lifespan. Index
refresh is asynchronous, so queries poll until the expected state is reached.
"""

import asyncio
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app

DOCS = "/v1/users/dev/projects/demo/docs"
SEARCH = "/v1/users/dev/projects/demo/search"

PLAN_BODY: dict[str, object] = {
    "type": "plan",
    "slug": "p1",
    "title": "Alpha Plan",
    "sections": [{"anchor": "intro", "heading": "Introduction", "level": 2}],
    "phases": [{"slug": "build", "name": "Build Stage", "tasks": [{"text": "t1"}]}],
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[str]:
    """Run the app on a loopback uvicorn server (full lifespan); yield its base URL."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def _poll_hits(
    client: httpx.AsyncClient, q: str, *, project: str = "demo", want: bool = True
) -> list[dict[str, object]]:
    """Poll search until hits are (non-)empty — the index refreshes asynchronously."""
    url = f"/v1/users/dev/projects/{project}/search"
    for _ in range(100):
        r = await client.get(url, params={"q": q})
        assert r.status_code == 200
        hits = r.json()["hits"]
        if bool(hits) == want:
            return hits
        await asyncio.sleep(0.02)
    raise AssertionError(f"search {q!r} want_hits={want} not reached")


async def test_search_endpoint_finds_title_heading_phase(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        title = await _poll_hits(client, "alpha")
        assert any(h["kind"] == "title" and h["slug"] == "p1" for h in title)
        sec = await _poll_hits(client, "introduction")
        assert any(h["kind"] == "section" and h["anchor"] == "intro" for h in sec)
        phase = await _poll_hits(client, "build stage")
        assert any(h["kind"] == "phase" and h["anchor"] == "build" for h in phase)


async def test_search_reflects_mutation(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await _poll_hits(client, "introduction")
        # A new section's heading becomes searchable via the event-fed index.
        await client.post(
            f"{DOCS}/p1/sections",
            json={"anchor": "design", "heading": "Design Notes", "level": 2},
        )
        hits = await _poll_hits(client, "design notes")
        assert any(h["anchor"] == "design" for h in hits)


async def test_search_scope_isolation(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await _poll_hits(client, "alpha")  # present under demo
        # The same query in a sibling project sees nothing.
        r = await client.get(
            "/v1/users/dev/projects/other/search", params={"q": "alpha"}
        )
        assert r.status_code == 200
        assert r.json()["hits"] == []


async def test_search_reflects_delete(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        r = await client.post(DOCS, json=PLAN_BODY)
        rev = r.headers["etag"]
        await _poll_hits(client, "alpha")
        deleted = await client.delete(f"{DOCS}/p1", headers={"If-Match": rev})
        assert deleted.status_code == 204
        # The event-fed index drops the entry; the hit disappears.
        await _poll_hits(client, "alpha", want=False)


async def test_search_requires_query(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        assert (await client.get(SEARCH)).status_code == 422  # q is required
        # q is bounded, so a pathological query is rejected, not scanned.
        too_long = await client.get(SEARCH, params={"q": "x" * 201})
        assert too_long.status_code == 422


async def test_user_search_spans_multiple_projects(live_server: str) -> None:
    """GET /v1/users/{uid}/search returns hits from all projects, with project_name."""
    docs_other = "/v1/users/dev/projects/other/docs"
    user_search = "/v1/users/dev/search"
    plan_other: dict[str, object] = {
        "type": "plan",
        "slug": "q1",
        "title": "Beta Plan",
    }
    async with httpx.AsyncClient(base_url=live_server) as client:
        # Seed one doc in each of two projects.
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(docs_other, json=plan_other)

        # Poll until both are indexed (index is event-fed, so async).
        async def _both_visible() -> bool:
            r = await client.get(user_search, params={"q": "plan"})
            if r.status_code != 200:
                return False
            slugs = {h["slug"] for h in r.json()["hits"]}
            return "p1" in slugs and "q1" in slugs

        for _ in range(100):
            if await _both_visible():
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("user search did not return hits from both projects")

        r = await client.get(user_search, params={"q": "plan"})
        assert r.status_code == 200
        hits = r.json()["hits"]
        projects_hit = {h["project"] for h in hits}
        assert "demo" in projects_hit
        assert "other" in projects_hit

        # project_name is populated: registry has no display name set, so it falls
        # back to the project slug.
        for h in hits:
            assert h["project_name"] == h["project"]

    # Endpoint also requires q.
    async with httpx.AsyncClient(base_url=live_server) as client:
        assert (await client.get(user_search)).status_code == 422


async def test_user_search_is_fuzzy_multiterm(live_server: str) -> None:
    """Whitespace terms each match as a subsequence: 'httpx aio' finds a heading
    'HTTPX vs aiohttp', and 'hpx' finds the title 'HTTPX migration'."""
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "h1",
                "title": "HTTPX migration",
                "sections": [
                    {"anchor": "cmp", "heading": "HTTPX vs aiohttp", "level": 2}
                ],
            },
        )
        hits = await _poll_hits(client, "httpx aio")
        assert any(h["kind"] == "section" and h["anchor"] == "cmp" for h in hits)
        hits2 = await _poll_hits(client, "hpx")
        assert any(h["kind"] == "title" and h["slug"] == "h1" for h in hits2)


async def test_user_search_does_not_match_project_display_name_or_slug(
    live_server: str,
) -> None:
    """Search is document-scoped only: a query matching only a project's display
    name, or only its slug, surfaces no hit for that project — even once the
    project's one doc is fully indexed."""
    user_search = "/v1/users/dev/search"
    async with httpx.AsyncClient(base_url=live_server) as client:
        # A project exists only if it has a doc; then give it a display name whose
        # words never appear in that doc's title/headings.
        await client.post(
            "/v1/users/dev/projects/other/docs",
            json={"type": "plan", "slug": "q1", "title": "Beta Plan"},
        )
        named = await client.put(
            "/v1/users/dev/projects/other/name",
            json={"name": "Onboarding Restructure"},
        )
        assert named.status_code == 200

        # Confirm the doc (and hence its project) is indexed before asserting
        # absence, so a false negative can't be mistaken for indexing lag.
        async def _indexed() -> bool:
            r = await client.get(user_search, params={"q": "beta"})
            if r.status_code != 200:
                return False
            return any(h["slug"] == "q1" for h in r.json()["hits"])

        for _ in range(100):
            if await _indexed():
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("doc was not indexed")

        # The display name matches nothing in the doc, so no hit surfaces.
        r = await client.get(user_search, params={"q": "onboarding restruct"})
        assert r.status_code == 200
        assert r.json()["hits"] == []

        # Neither does the bare project slug.
        r = await client.get(user_search, params={"q": "other"})
        assert r.status_code == 200
        assert r.json()["hits"] == []


async def test_user_search_ranks_substring_above_scatter(live_server: str) -> None:
    """Scoring favors a contiguous substring over a scattered subsequence: 'beta'
    matches both 'Beta plan' (substring) and 'Bears eat tasty apples' (scatter), and
    the substring title must rank first."""
    url = "/v1/users/dev/projects/demo/search"
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(
            DOCS, json={"type": "plan", "slug": "r1", "title": "Beta plan"}
        )
        await client.post(
            DOCS, json={"type": "plan", "slug": "r2", "title": "Bears eat tasty apples"}
        )
        order: list[str] = []
        for _ in range(100):
            r = await client.get(url, params={"q": "beta"})
            assert r.status_code == 200
            titles = [h["slug"] for h in r.json()["hits"] if h["kind"] == "title"]
            if {"r1", "r2"} <= set(titles):
                order = titles
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("both docs were not indexed")
        assert order[0] == "r1"  # the contiguous-substring match leads
        assert order.index("r1") < order.index("r2")
