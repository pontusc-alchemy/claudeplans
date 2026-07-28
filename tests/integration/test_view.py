"""In-process tests for the live-view pages, assets, and SSE stream.

feed + render_cache are built in create_app (not only in lifespan), so the
non-streaming routes work under a plain ASGITransport. The SSE routes do NOT:
httpx's ASGITransport buffers the whole response before returning, so a stream that
yields one frame and then blocks for the next deadlocks. The SSE tests therefore
run the app on a real loopback uvicorn server (which streams incrementally), driven
by httpx over TCP, with short timeouts so a missing frame fails fast.
"""

import asyncio
import json
import socket
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from httpx import ASGITransport

from claudeplans import templates
from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE
from claudeplans_contracts import Document, Phase, Section, Task
from claudeplans_contracts.enums import DocType, SectionPlacement

DOCS = "/v1/users/dev/projects/demo/docs"
VIEW = "/v1/users/dev/projects/demo/docs/p1/view"
EVENTS = "/v1/users/dev/projects/demo/docs/p1/events"
LINEAGE = "/v1/users/dev/projects/demo/"

PLAN_BODY: dict[str, object] = {
    "type": "plan",
    "slug": "p1",
    "title": "Plan One",
    "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
}


def _client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _read_frame(lines: AsyncIterator[str]) -> list[str]:
    """Accumulate SSE lines up to the blank-line frame boundary."""
    frame: list[str] = []
    async for line in lines:
        if line == "":
            return frame
        frame.append(line)
    return frame


async def _read_doc_frame(lines: AsyncIterator[str]) -> list[str]:
    """Read the next doc-body (`event: message`) frame, skipping the interleaved
    `event: sidebar` frames the live sidebar emits on connect and on every change."""
    while True:
        frame = await _read_frame(lines)
        if "event: sidebar" not in frame:
            return frame


async def test_view_page_renders(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        assert 'id="doc"' in body
        assert 'hx-ext="sse,morph"' in body
        assert "Plan One" in body
        assert "/assets/js/htmx.min.js" in body
        assert "/assets/js/idiomorph-ext.min.js" in body
        assert "/assets/js/sse.js" in body
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-eval" not in csp


async def test_view_page_shows_version_footer(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert '<footer class="app-version">dev</footer>' in resp.text


async def test_assets_served(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await client.get("/assets/js/htmx.min.js")
        assert resp.status_code == 200
        assert resp.text.startswith("var htmx")
        # Assets revalidate every load (ETag) so a redeploy's CSS/JS isn't stale-cached.
        assert resp.headers["cache-control"] == "no-cache"


async def test_idiomorph_ext_served(tmp_path: Path) -> None:
    # The htmx-integration build (not the core morph) is what registers the "morph"
    # extension the template's hx-ext="...,morph" requires, so it must be served.
    async with _client(tmp_path) as client:
        resp = await client.get("/assets/js/idiomorph-ext.min.js")
        assert resp.status_code == 200
        assert "defineExtension" in resp.text


async def test_script_injection_neutralized_in_page(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "<script>alert(1)</script>",
                "level": 2,
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        # The vendored <script src=...> tags are fine; the injected inline script must
        # not survive as an executable element.
        assert "<script>alert(1)</script>" not in resp.text


async def test_morph_target_id_cannot_be_spoofed(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "# Pwned {#doc-status .pill .done}",
                "level": 2,
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        # Only the template's own trusted #doc-status survives; the attr_list-injected
        # duplicate is stripped, so idiomorph's id-matching can't be corrupted.
        assert resp.text.count('id="doc-status"') == 1


def test_research_body_has_no_phase_blocks() -> None:
    # Research docs carry no phases, so the body renders neither the phase overview
    # nor any phase block (both are guarded by `{% if phases %}` / the block flow) —
    # only its prose sections.
    doc = Document(
        type=DocType.research,
        project="demo",
        slug="r1",
        title="Research One",
        owner_id="dev",
    )
    body = templates.render_doc_body(doc)
    assert 'id="phase-' not in body


async def test_lineage_page_renders(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        await client.post(
            DOCS, json={"type": "plan", "slug": "p2", "title": "Plan Two"}
        )  # no research ref -> standalone, under the "Plans" heading
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200
        body = resp.text
        assert 'id="lineage"' in body
        assert "Research One" in body
        assert "Plan One" in body
        # The plan link nests under the research node, so it follows it in the markup.
        assert body.index("Research One") < body.index("Plan One")
        # Human-facing section headings (not the internal "lineage"/"Unlinked plans").
        assert "<h2>Research</h2>" in body
        assert "<h2>Plans</h2>" in body
        assert "Unlinked plans" not in body


async def test_view_page_has_sidebar_with_active_doc(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        body = resp.text
        assert 'class="sidebar"' in body
        assert 'id="user-select"' in body  # the user switcher
        assert "/assets/js/ui.js" in body  # same-origin switcher script
        assert 'aria-current="page"' in body  # the open doc is highlighted
        assert 'href="/v1/users/dev/projects/demo/"' not in body  # title is not a link
        # CSP must be unchanged by the sidebar work.
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-eval" not in csp


async def test_lineage_page_has_sidebar(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200
        body = resp.text
        assert 'class="sidebar"' in body
        assert 'id="user-select"' in body
        assert 'class="sidebar-project current"' in body  # the project still highlights
        assert "aria-current" not in body  # no doc is open on the lineage page


async def test_user_landing_renders(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get("/v1/users/dev/")
        assert resp.status_code == 200
        body = resp.text
        assert 'id="landing"' in body  # the welcome pane
        assert 'class="sidebar"' in body
        assert 'id="user-select"' in body
        assert 'value="dev"' in body  # switcher lists the doc owner
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp


async def test_switcher_marks_current_user_selected(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get("/v1/users/dev/")
        # the current user's option is pre-selected in the switcher
        assert '<option value="dev" selected>' in resp.text


async def test_sidebar_shows_only_current_users_projects(tmp_path: Path) -> None:
    # Seed another user's doc directly in storage. The dev sidebar must NOT list
    # her project (only the current user's projects show by default); the switcher
    # still offers her as a user to switch to.
    seed = FilesystemRepository(tmp_path)
    await seed.put(
        "alice/secret/p1",
        {
            "type": "plan",
            "project": "secret",
            "slug": "p1",
            "title": "Alice Secret Title",
            "owner_id": "alice",
        },
        CREATE,
    )
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # dev's own doc
        resp = await client.get("/v1/users/dev/")
        body = resp.text
        assert "Alice Secret Title" not in body  # her doc absent from dev's tree
        assert 'value="alice"' in body  # but she is a switcher option


async def test_root_shows_user_picker(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # dev now owns a doc
        resp = await client.get("/", follow_redirects=False)
        assert resp.status_code == 200  # a page now, not a 307 redirect
        body = resp.text
        assert 'id="user-picker"' in body
        assert 'href="/v1/users/dev/"' in body  # dev is listed and links to its tree
        # No sidebar on the picker (it's the pre-user-selection entry point).
        assert 'class="sidebar"' not in body
        # CSP parity with the rest of the view surface.
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-eval" not in csp


async def test_entry_pages_show_logo(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        # Root picker
        picker = await client.get("/", follow_redirects=False)
        assert picker.status_code == 200
        assert 'class="logo"' in picker.text
        assert 'class="sr-only">Claudeplans</span>' in picker.text
        # Per-user landing: text only, no logo (the logo is the picker's job).
        landing = await client.get("/v1/users/dev/")
        assert landing.status_code == 200
        assert 'class="logo"' not in landing.text
        assert "Select a plan from the sidebar" in landing.text


async def test_switcher_target_resolves(tmp_path: Path) -> None:
    # The switcher navigates to /v1/users/<uid>/; confirm that target is a real 200
    # page (not a 404).
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert 'data-switch-base="/v1/users/"' in resp.text
        landing = await client.get("/v1/users/dev/")
        assert landing.status_code == 200


async def test_lineage_page_skips_unloadable_doc(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # one good doc
        # A poison doc the current model rejects, written straight to the store
        # (repo.list returns it; get_document raises ValidationError on the body).
        poison = tmp_path / "dev" / "demo" / "bad.json"
        poison.write_text(
            json.dumps(
                {
                    "rev": "1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "document": {
                        "type": "plan",
                        "project": "demo",
                        "slug": "bad",
                        "title": "bad",
                        "owner_id": "dev",
                        "BOGUS_FIELD": 1,
                    },
                }
            )
        )
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200  # was 422 before the skip
        assert "Plan One" in resp.text  # the good doc still renders
        assert "bad" not in resp.text  # the poison doc is skipped, not rendered


async def test_lineage_json_skips_unloadable_doc(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # one good doc
        poison = tmp_path / "dev" / "demo" / "bad.json"
        poison.write_text(
            json.dumps(
                {
                    "rev": "1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "document": {
                        "type": "plan",
                        "project": "demo",
                        "slug": "bad",
                        "title": "bad",
                        "owner_id": "dev",
                        "BOGUS_FIELD": 1,
                    },
                }
            )
        )
        resp = await client.get("/v1/users/dev/projects/demo/lineage")
        assert resp.status_code == 200  # JSON endpoint must also skip, not 422
        assert "p1" in resp.text  # the good plan is in the lineage payload
        assert "bad" not in resp.text  # poison skipped


async def test_doc_view_has_single_aria_current(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        body = resp.text
        # Exactly one element is the current page: the open doc in the sidebar.
        assert body.count('aria-current="page"') == 1
        # The containing project is marked active-ancestor (class), not current-page.
        assert 'class="sidebar-project current"' in body


# --- sub-plan lineage trail -------------------------------------------------


async def test_view_page_shows_lineage_trail_for_child_plan(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        body = resp.text
        assert 'class="doc-lineage-trail"' in body
        assert "Research One" in body  # the parent's title labels the trail
        assert "▸" in body  # the separator between parent and current
        # The parent link resolves to the research doc's own view page.
        assert 'href="/v1/users/dev/projects/demo/docs/r1/view"' in body


async def test_view_page_lineage_trail_absent_for_root_research(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        resp = await client.get(f"{DOCS}/r1/view")
        assert resp.status_code == 200
        assert "doc-lineage-trail" not in resp.text  # research has no parent lineage


async def test_view_page_lineage_trail_absent_for_standalone_plan(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # a plan with no primary_research_ref
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert "doc-lineage-trail" not in resp.text


async def test_view_page_lineage_trail_degrades_on_dangling_ref(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        research = await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        rev = research.headers["etag"]
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        # Delete the parent so the plan's primary_research_ref now dangles.
        deleted = await client.delete(f"{DOCS}/r1", headers={"If-Match": rev})
        assert deleted.status_code == 204
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert "doc-lineage-trail" not in resp.text  # dangling ref degrades to no trail


# --- sub-doc index (parent research page) -----------------------------------


async def test_view_page_shows_subdoc_index_on_parent_research(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        for slug, title in (("p1", "Plan One"), ("p2", "Plan Two")):
            await client.post(
                DOCS,
                json={
                    "type": "plan",
                    "slug": slug,
                    "title": title,
                    "research_refs": ["r1"],
                    "primary_research_ref": "r1",
                },
            )
        resp = await client.get(f"{DOCS}/r1/view")
        assert resp.status_code == 200
        body = resp.text
        assert 'class="doc-subdoc-index"' in body
        assert "Plan One" in body and "Plan Two" in body
        # Each child links to its own view page, listed in slug order.
        assert 'href="/v1/users/dev/projects/demo/docs/p1/view"' in body
        assert 'href="/v1/users/dev/projects/demo/docs/p2/view"' in body
        assert body.index("Plan One") < body.index("Plan Two")


async def test_view_page_subdoc_index_absent_for_childless_research(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        resp = await client.get(f"{DOCS}/r1/view")
        assert resp.status_code == 200
        assert "doc-subdoc-index" not in resp.text  # no children -> no index


async def test_view_page_subdoc_index_absent_for_plan(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # a plan is a leaf, never a parent
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert "doc-subdoc-index" not in resp.text


# --- SSE: needs a real socket server (ASGITransport can't stream) -----------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[str]:
    """Run the app on a loopback uvicorn server; yield its base URL."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for startup so the first request never races the bind.
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def test_sse_emits_on_connect_and_on_mutation(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        async with client.stream("GET", EVENTS) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = r.aiter_lines()
            # Snapshot-on-connect frame.
            first = await asyncio.wait_for(_read_frame(lines), 5)
            assert "event: message" in first
            assert any('id="doc-title"' in line for line in first)
            # The SSE morph payload is the #doc body only — no sidebar chrome.
            assert not any("user-select" in line for line in first)
            # A mutation publishes an Event the already-subscribed stream receives.
            resp = await client.put(
                f"{DOCS}/p1/phases/a/status", json={"status": "done"}
            )
            assert resp.status_code == 200
            nxt = await asyncio.wait_for(_read_doc_frame(lines), 5)
            assert any('phase-a-status" class="pill done"' in line for line in nxt)


async def test_view_page_lineage_trail_not_in_sse_morph_payload(
    live_server: str,
) -> None:
    # The lineage trail is shell chrome above <main id="doc">, outside the SSE morph
    # target — so the snapshot morph frame (the #doc body only) must not carry it,
    # even for a child plan whose page shell renders a real lineage trail.
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        async with client.stream("GET", EVENTS) as r:
            lines = r.aiter_lines()
            first = await asyncio.wait_for(_read_frame(lines), 5)
            assert "event: message" in first  # the doc-body snapshot frame
            assert not any("doc-lineage-trail" in line for line in first)


async def test_view_page_subdoc_index_not_in_sse_morph_payload(
    live_server: str,
) -> None:
    # The sub-doc index is shell chrome above <main id="doc">, outside the SSE morph
    # target — so the snapshot morph frame (the #doc body only) must not carry it,
    # even for a research doc whose page shell renders a real index.
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        async with client.stream(
            "GET", "/v1/users/dev/projects/demo/docs/r1/events"
        ) as r:
            lines = r.aiter_lines()
            first = await asyncio.wait_for(_read_frame(lines), 5)
            assert "event: message" in first  # the doc-body snapshot frame
            assert not any("doc-subdoc-index" in line for line in first)


async def test_reconnect_resyncs(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.put(f"{DOCS}/p1/phases/a/status", json={"status": "done"})
        # A fresh connection's snapshot already reflects the mutation (no replay).
        async with client.stream("GET", EVENTS) as r:
            first = await asyncio.wait_for(_read_frame(r.aiter_lines()), 5)
            assert any('phase-a-status" class="pill done"' in line for line in first)


async def test_sse_injection_neutralized_end_to_end(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "<script>alert(1)</script>",
                "level": 2,
            },
        )
        # The snapshot frame is the sanitized body; the injected script must not
        # survive as an executable element in the pushed stream.
        async with client.stream("GET", EVENTS) as r:
            first = await asyncio.wait_for(_read_frame(r.aiter_lines()), 5)
            assert not any("<script>alert(1)</script>" in line for line in first)


async def test_delete_while_watching_emits_removed_frame(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        resp = await client.post(DOCS, json=PLAN_BODY)
        rev = resp.headers["etag"]
        async with client.stream("GET", EVENTS) as r:
            lines = r.aiter_lines()
            await asyncio.wait_for(_read_frame(lines), 5)  # drain the snapshot frame
            deleted = await client.delete(f"{DOCS}/p1", headers={"If-Match": rev})
            assert deleted.status_code == 204
            frame = await asyncio.wait_for(_read_doc_frame(lines), 5)
            assert any("This document was removed." in line for line in frame)


async def test_sidebar_collapsible_and_indicators(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        # Doc-view page: the current project's <details> is open; the doc entry
        # carries a status dot + type marker.
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        body = resp.text
        assert '<details data-project="demo" open>' in body  # current project expanded
        assert 'class="status-dot status-draft"' in body  # plan default status
        assert 'class="doc-type doc-type-plan"' in body  # type marker
        # The dot/marker are visual-only; screen readers get the status + type
        # via a visually-hidden span (the color-only-meaning a11y fix).
        assert 'class="sr-only">plan, draft: ' in body


async def test_sse_snapshot_on_corrupt_doc_emits_unavailable_frame(
    live_server: str, tmp_path: Path
) -> None:
    # Pre-corrupt the target doc before connecting so the snapshot read raises;
    # the stream must emit the "unavailable" frame (not tear the connection).
    corrupt = tmp_path / "dev" / "demo" / "p1.json"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text(
        json.dumps(
            {
                "rev": "2",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "document": "not-a-dict",
            }
        )
    )
    async with httpx.AsyncClient(base_url=live_server) as client:
        async with client.stream("GET", EVENTS) as r:
            assert r.status_code == 200
            frame = await asyncio.wait_for(_read_frame(r.aiter_lines()), 5)
            assert any("currently unavailable" in line for line in frame)


async def test_sidebar_indicators_non_default_status_and_research_type(
    tmp_path: Path,
) -> None:
    # A research doc with active status must show the correct status dot and type
    # marker (non-default status + non-plan type — both distinct from the plan/draft
    # case already covered by test_sidebar_collapsible_and_indicators).
    async with _client(tmp_path) as client:
        await client.post(
            DOCS,
            json={"type": "research", "slug": "r9", "title": "R Nine"},
        )
        # Advance the status to active via the status route.
        await client.put(f"{DOCS}/r9/status", json={"status": "active"})
        # GET the project lineage page — all docs show in the sidebar.
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200
        body = resp.text
        assert 'class="status-dot status-active"' in body
        assert 'class="doc-type doc-type-research"' in body


async def test_lineage_json_unlinked_plan_carries_status_and_type(
    tmp_path: Path,
) -> None:
    # Each unlinked-plan entry in the JSON lineage must expose `status` and `type`
    # so callers never have to fetch the full doc to render a label.
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # slug=p1, type=plan, status=draft
        resp = await client.get("/v1/users/dev/projects/demo/lineage")
        assert resp.status_code == 200
        data = resp.json()
        plan = next(p for p in data["unlinked_plans"] if p["slug"] == "p1")
        assert plan["type"] == "plan"
        assert plan["status"] == "draft"


async def test_sidebar_shows_archived_doc_collapsed_and_excluded_from_main_tree(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # slug=p1, active
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "old",
                "title": "Old Plan",
                "status": "archived",
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        body = resp.text
        # Collapsed (no `open`), keyed into ui.js persistence via data-project.
        opening_tag = '<details class="archived-group" data-project="demo//archived">'
        assert opening_tag in body
        assert "<summary" in body and "Archived (1)" in body
        # The archived doc appears once, inside the archived group only.
        assert body.count("Old Plan") == 1
        archived_index = body.index(opening_tag)
        assert body.index("Old Plan") > archived_index
        # The active doc stays in the main (non-archived) tree.
        assert body.index("Plan One") < archived_index


async def test_sidebar_archived_group_auto_expands_for_current_doc(
    tmp_path: Path,
) -> None:
    # Viewing an archived doc must render its group expanded, or the
    # aria-current highlight would be hidden inside a collapsed <details>.
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "old",
                "title": "Old Plan",
                "status": "archived",
            },
        )
        resp = await client.get(f"{DOCS}/old/view")
        assert resp.status_code == 200
        assert (
            '<details class="archived-group" data-project="demo//archived" open>'
            in resp.text
        )


async def test_sidebar_no_archived_group_when_no_archived_docs(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert "archived-group" not in resp.text


async def test_project_lineage_page_shows_archived_group(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "plan", "slug": "p2", "title": "Plan Two"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "old",
                "title": "Old Plan",
                "status": "archived",
            },
        )
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200
        # Scope to the lineage main content only — the sidebar carries its own
        # (separately tested) archived group and would otherwise confound the index
        # comparisons below.
        main = resp.text.split('<main class="lineage"', 1)[1]
        assert '<details class="archived-group">' in main
        archived_index = main.index('<details class="archived-group">')
        assert main.index("Old Plan") > archived_index
        assert main.index("Plan Two") < archived_index


async def test_lineage_json_excludes_archived_docs(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)  # slug=p1, active
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "old",
                "title": "Old Plan",
                "status": "archived",
            },
        )
        resp = await client.get("/v1/users/dev/projects/demo/lineage")
        assert resp.status_code == 200
        data = resp.json()
        assert [p["slug"] for p in data["unlinked_plans"]] == ["p1"]


# --- templates: field-map rendering ------------------------------------------


def test_phase_prose_rendered_from_fields() -> None:
    # Prose now comes from first-class Phase fields, not a coupled section blob.
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="dev",
        phases=[
            Phase(
                slug="a",
                name="Alpha",
                intro="The intro prose.",
                tasks=[Task(text="do the thing")],
                exit_criteria="All green.",
                notes="!!! note\n    A revision card.",
            )
        ],
    )
    body = templates.render_doc_body(doc)
    assert "The intro prose." in body
    assert "<h3>Exit criteria</h3>" in body
    assert "All green." in body
    assert "A revision card." in body
    # Full intra-phase order: intro -> Checklist -> Exit criteria -> notes. Pin every
    # boundary so a future template reorder can't pass this silently.
    assert (
        body.index("The intro prose.")
        < body.index("<h3>Checklist</h3>")
        < body.index("<h3>Exit criteria</h3>")
        < body.index("A revision card.")
    )


def test_phase_prose_injection_is_sanitized() -> None:
    # The new first-class prose fields are a separately-settable HTML sink; confirm
    # they get the same nh3 treatment as section bodies — no executable script, and
    # no attr_list-forged stable fragment id to corrupt idiomorph.
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="dev",
        phases=[
            Phase(
                slug="a",
                name="Alpha",
                intro="<script>alert(1)</script>",
                notes="# Pwned {#doc-status .pill .done}",
            )
        ],
    )
    body = templates.render_doc_body(doc)
    assert "<script>alert(1)</script>" not in body
    # The attr_list-injected id is stripped, so the trusted #doc-status stays unique.
    assert body.count('id="doc-status"') == 1


def test_lead_and_trail_sections_bracket_the_phase_group() -> None:
    # placement=lead renders before all phases; placement=trail after them.
    doc = Document(
        type=DocType.plan,
        project="demo",
        slug="p1",
        title="Plan One",
        owner_id="dev",
        sections=[
            Section(anchor="lead1", heading="Lead", placement=SectionPlacement.lead),
            Section(anchor="trail1", heading="Trail", placement=SectionPlacement.trail),
        ],
        phases=[Phase(slug="a", name="Alpha")],
    )
    body = templates.render_doc_body(doc)
    assert (
        body.index('id="section-lead1"')
        < body.index('id="phase-a"')
        < body.index('id="section-trail1"')
    )


def test_no_render_time_split_helpers_remain() -> None:
    # The string-matching split functions were deleted; render is a pure field map.
    assert not hasattr(templates, "_split_admonitions")
    assert not hasattr(templates, "_split_exit_criteria")
