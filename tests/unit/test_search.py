"""Unit tests for the in-memory SearchIndex: build, query, and event-freshness.

Drives the real SearchIndex against a real FilesystemRepository + EventFeed (no web
stack): `run` builds from storage then keeps fresh off the feed, exactly as the
lifespan wires it. The `_running_index` helper starts the consumer, waits for the
initial build, then tears it down via the feed's shutdown sentinel.
"""

import asyncio
import unicodedata
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path

from claudeplans.events import Event, EventFeed
from claudeplans.search import SearchIndex
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE, Repository, _Create
from claudeplans_contracts import Document, Phase, Section, document_key
from claudeplans_contracts.enums import DocStatus, DocType, PhaseStatus


def _repo(tmp_path: Path) -> FilesystemRepository:
    return FilesystemRepository(str(tmp_path))


def _doc(
    slug: str,
    title: str,
    *,
    project: str = "demo",
    owner: str = "dev",
    status: DocStatus = DocStatus.draft,
    sections: Sequence[tuple[str, str]] = (),
    phases: Sequence[tuple[str, str]] = (),
) -> Document:
    return Document(
        type=DocType.plan,
        project=project,
        slug=slug,
        title=title,
        owner_id=owner,
        status=status,
        sections=[Section(anchor=a, heading=h, level=2) for a, h in sections],
        phases=[
            Phase(slug=s, name=n, status=PhaseStatus.todo, tasks=[]) for s, n in phases
        ],
    )


async def _put(
    repo: Repository, doc: Document, expected_rev: str | _Create = CREATE
) -> str:
    return await repo.put(
        document_key(doc.owner_id, doc.project, doc.slug),
        doc.model_dump(mode="json"),
        expected_rev,
    )


@asynccontextmanager
async def _running_index(
    repo: Repository,
) -> AsyncIterator[tuple[SearchIndex, EventFeed]]:
    feed = EventFeed()
    index = SearchIndex()
    task = asyncio.create_task(index.run(repo, feed))
    await index.ready()
    try:
        yield index, feed
    finally:
        feed.close()
        await task


async def _until(pred: Callable[[], object], timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


async def test_build_indexes_titles_headings_phases(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(
        repo,
        _doc(
            "p1",
            "Alpha Plan",
            sections=[("intro", "Introduction")],
            phases=[("build", "Build Stage")],
        ),
    )
    async with _running_index(repo) as (index, _):
        title = index.query("alpha").hits
        assert [(h.kind, h.slug, h.anchor) for h in title] == [("title", "p1", None)]
        sec = index.query("introduction").hits
        assert [(h.kind, h.anchor) for h in sec] == [("section", "intro")]
        phase = index.query("build stage").hits
        assert [(h.kind, h.anchor) for h in phase] == [("phase", "build")]


async def test_query_is_case_insensitive_and_substring(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(repo, _doc("p1", "Alpha Plan"))
    async with _running_index(repo) as (index, _):
        assert index.query("ALPHA").hits
        assert index.query("lph").hits  # substring, not just prefix
        assert index.query("zzz").hits == []


async def test_blank_query_returns_no_hits(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(repo, _doc("p1", "Alpha Plan"))
    async with _running_index(repo) as (index, _):
        assert index.query("   ").hits == []


async def test_prefix_scopes_to_user_and_project(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(repo, _doc("p1", "Shared Title", project="demo"))
    await _put(repo, _doc("p2", "Shared Title", project="other"))
    await _put(repo, _doc("p3", "Shared Title", owner="alice", project="demo"))
    async with _running_index(repo) as (index, _):
        scoped = {h.key for h in index.query("shared", prefix="dev/demo/").hits}
        assert scoped == {"dev/demo/p1"}  # same project, this owner only
        # The OWNER segment isolates too: alice/demo does not bleed into dev/demo.
        alice = {h.key for h in index.query("shared", prefix="alice/demo/").hits}
        assert alice == {"alice/demo/p3"}
        assert len(index.query("shared").hits) == 3  # unscoped sees every doc


async def test_index_reflects_create_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    async with _running_index(repo) as (index, feed):
        assert index.query("gamma").hits == []
        rev = await _put(repo, _doc("g1", "Gamma Plan"))
        feed.publish(Event(key=document_key("dev", "demo", "g1"), rev=rev))
        await _until(lambda: index.query("gamma").hits)


async def test_index_reflects_update_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev = await _put(repo, _doc("p1", "Old Title"))
    key = document_key("dev", "demo", "p1")
    async with _running_index(repo) as (index, feed):
        assert index.query("old").hits
        new_rev = await _put(repo, _doc("p1", "New Title"), expected_rev=rev)
        feed.publish(Event(key=key, rev=new_rev))
        await _until(lambda: index.query("new").hits)
        assert index.query("old").hits == []  # stale title dropped


async def test_archived_doc_invisible_until_unarchived(tmp_path: Path) -> None:
    # Archived docs stay IN the index but never match; flipping the status back
    # surfaces them again on the same running index — no rebuild involved.
    repo = _repo(tmp_path)
    rev = await _put(repo, _doc("p1", "Retired Plan"))
    key = document_key("dev", "demo", "p1")
    async with _running_index(repo) as (index, feed):
        assert index.query("retired").hits
        rev = await _put(
            repo,
            _doc("p1", "Retired Plan", status=DocStatus.archived),
            expected_rev=rev,
        )
        feed.publish(Event(key=key, rev=rev))
        await _until(lambda: index.query("retired").hits == [])
        rev = await _put(repo, _doc("p1", "Retired Plan"), expected_rev=rev)
        feed.publish(Event(key=key, rev=rev))
        await _until(lambda: index.query("retired").hits)


async def test_index_reflects_delete_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    rev = await _put(repo, _doc("p1", "Doomed Plan"))
    key = document_key("dev", "demo", "p1")
    async with _running_index(repo) as (index, feed):
        assert index.query("doomed").hits
        await repo.delete(key, rev)
        feed.publish(Event(key=key, rev=rev))
        await _until(lambda: index.query("doomed").hits == [])


async def test_rebuild_skips_unreadable_doc_and_stays_live(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(repo, _doc("good", "Findable Plan"))
    # A valid envelope whose body cannot load (future schema -> migrate raises): it
    # lists, so the scan reaches it, but get_document raises a non-NotFound error.
    await repo.put(
        document_key("dev", "demo", "poison"),
        {
            "schema_version": 999,
            "type": "plan",
            "project": "demo",
            "slug": "poison",
            "title": "Poison",
            "owner_id": "dev",
        },
        CREATE,
    )
    async with _running_index(repo) as (index, feed):
        # The good doc indexed despite its poison sibling (build didn't abort).
        assert [h.slug for h in index.query("findable").hits] == ["good"]
        # And the freshness consumer is still alive — a later write is indexed.
        rev = await _put(repo, _doc("g2", "Gamma Later"))
        feed.publish(Event(key=document_key("dev", "demo", "g2"), rev=rev))
        await _until(lambda: index.query("gamma later").hits)


async def test_research_doc_indexes_title_and_headings(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(
        repo,
        Document(
            type=DocType.research,
            project="demo",
            slug="r1",
            title="Research Doc",
            owner_id="dev",
            sections=[Section(anchor="bg", heading="Background", level=2)],
        ),
    )
    async with _running_index(repo) as (index, _):
        assert [h.kind for h in index.query("research doc").hits] == ["title"]
        assert [h.anchor for h in index.query("background").hits] == ["bg"]


async def test_hits_order_title_first_then_anchor(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # "spec" matches the title, a phase, and two sections sharing a heading.
    await _put(
        repo,
        _doc(
            "p1",
            "Spec Plan",
            sections=[("a", "Spec Details"), ("b", "Spec Details")],
            phases=[("impl", "Spec Impl")],
        ),
    )
    async with _running_index(repo) as (index, _):
        hits = index.query("spec").hits
        # Within one doc: title before phase before section.
        assert [h.kind for h in hits] == ["title", "phase", "section", "section"]
        # Duplicate-heading sections fall back to anchor order (deterministic).
        assert [h.anchor for h in hits if h.kind == "section"] == ["a", "b"]


async def test_query_normalizes_unicode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    await _put(repo, _doc("p1", "Café Plan"))  # title stored precomposed (NFC)
    async with _running_index(repo) as (index, _):
        decomposed = unicodedata.normalize("NFD", "café")  # different bytes, same text
        assert decomposed != "café"
        assert [h.slug for h in index.query(decomposed).hits] == ["p1"]
