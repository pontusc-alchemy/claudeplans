"""Search — title + section/phase heading search over an in-memory index.

A module (not a package) until full-text justifies a `SearchIndex` Protocol: this
is substring matching over document titles and section/phase HEADINGS only, no
body full-text. The index is built from the storage listing at startup and kept
fresh by subscribing to the events feed — every change Event triggers a reload of
that one document, so the index converges to current state with no periodic
rebuild. Full-text search (behind a `SearchIndex` Protocol) stays deferred.

The build enumerates docs via the storage listing (`repo.list`) and loads each
Document once to project out the searchable fields. Section/phase headings need the
parsed body anyway, so title/type/status come from that same loaded, validated
Document rather than from `ListEntry.metadata` — one source keeps the startup build
and the per-event refresh consistent.

Lossless subscription: the feed's default per-subscriber queue is bounded
drop-OLDEST (right for an SSE reader that converges per-doc), but this single
process-wide consumer indexes ALL docs, so a dropped Event for a distinct key would
leave that doc's entry permanently stale. It therefore subscribes with an unbounded
queue; the one long-lived consumer drains it promptly (a reload is one file read),
so unbounded growth would need a sustained write rate exceeding the reload rate —
not a real risk for this single-worker, single-user local tool.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass
from typing import Literal

from claudeplans_contracts import (
    DocStatus,
    DocType,
    Document,
    NotFound,
    SearchHit,
    SearchResults,
)

from . import core
from .events import EventFeed
from .storage.repository import Repository

logger = logging.getLogger(__name__)

# Hit-kind sort priority (a score tie-breaker only — ranking is by match score):
# a document's own title, then its phases, then its sections.
_KIND_ORDER: dict[str, int] = {"title": 1, "phase": 2, "section": 3}


def _fold(text: str) -> str:
    """Normalize (NFC) then casefold, so a decomposed query matches a precomposed
    heading (and vice versa) — `.casefold()` alone leaves canonical equivalents
    as distinct byte sequences, silently missing visually-identical non-ASCII text."""
    return unicodedata.normalize("NFC", text).casefold()


def _score_term(term: str, s: str) -> float | None:
    """Score one query `term` against an already-folded candidate `s` (higher is
    better); None when `term` is not even an in-order subsequence of `s`. A contiguous
    substring scores highest; a looser character scatter scores lower; an earlier,
    word-boundary-aligned match scores higher. This is the fzf-style fuzzy primitive:
    `term` need only appear as an in-order subsequence, so "hpx" matches "httpx"."""
    m = len(term)
    if m == 0:
        return 0.0
    sub = s.find(term)
    if sub != -1:
        first, span, contiguous = sub, m, True
    else:
        first = last = -1
        ti = 0
        for i, ch in enumerate(s):
            if ch == term[ti]:
                if first < 0:
                    first = i
                last = i
                ti += 1
                if ti == m:
                    break
        if ti < m:
            return None
        span, contiguous = last - first + 1, False
    tightness = m / span  # (0, 1]; 1.0 when the matched chars are contiguous
    boundary = 1.0 if first == 0 or not s[first - 1].isalnum() else 0.0
    score = tightness * 3.0 + boundary + 0.5 / (first + 1)
    if contiguous:
        score += 1.0
    return score


def _match(terms: list[str], text: str) -> float | None:
    """Total fuzzy score for `text` against every term (AND); None if any term misses.
    Splitting the query into whitespace terms is what lets "httpx aio" match
    "httpx vs aiohttp" even though that exact substring never occurs."""
    s = _fold(text)
    total = 0.0
    for term in terms:
        score = _score_term(term, s)
        if score is None:
            return None
        total += score
    return total


@dataclass(frozen=True, slots=True)
class _IndexedDoc:
    """The searchable projection of one document held in memory."""

    key: str
    project: str
    slug: str
    title: str
    doc_type: DocType
    status: DocStatus
    sections: list[tuple[str, str]]  # (heading, anchor)
    phases: list[tuple[str, str]]  # (name, slug)


def _project(key: str, doc: Document) -> _IndexedDoc:
    """Project a loaded Document into its searchable fields.

    Title/type/status come straight from the loaded, validated Document — the body
    is loaded for the section/phase headings regardless, so there is no body-free
    path to optimize and a single source keeps build and event-refresh consistent.
    """
    return _IndexedDoc(
        key=key,
        project=doc.project,
        slug=doc.slug,
        title=doc.title,
        doc_type=doc.type,
        status=doc.status,
        sections=[(s.heading, s.anchor) for s in doc.sections],
        phases=[(p.name, p.slug) for p in doc.phases],
    )


class SearchIndex:
    """In-memory title + heading index, built at startup and kept fresh via events.

    `run` is the lifespan task: it subscribes (eagerly, before the build, so a write
    during the build is queued not lost), does the initial full scan, signals
    readiness, then applies every change Event until the feed closes. `query` is a
    pure, synchronous read over the current snapshot — safe to call from a request
    handler with no await.
    """

    def __init__(self) -> None:
        self._docs: dict[str, _IndexedDoc] = {}
        self._ready = asyncio.Event()

    async def ready(self) -> None:
        """Block until the initial build has completed (set even if it failed)."""
        await self._ready.wait()

    async def run(self, repo: Repository, feed: EventFeed) -> None:
        """Build from storage, then apply change Events until the feed closes.

        Subscribes BEFORE building so an Event published mid-build is queued and
        applied afterwards (a redundant reload of current state is idempotent). The
        loop ends on the feed's shutdown sentinel.
        """
        with feed.subscribe(maxsize=0) as sub:
            try:
                await self._rebuild(repo)
            except Exception:
                # The initial scan must never kill the freshness consumer: even a
                # total build failure (e.g. the listing itself errors) leaves an empty
                # index that self-heals as subsequent writes arrive over the feed.
                logger.exception("search index: initial build failed")
            finally:
                # Always release waiters so startup never hangs on ready().
                self._ready.set()
            async for event in sub:
                try:
                    await self._apply(repo, event.key)
                except Exception:
                    # A long-lived consumer must survive a single bad reload; drop the
                    # one update (the next write to that key re-applies) and continue.
                    logger.exception("search index: failed to apply %r", event.key)

    async def _rebuild(self, repo: Repository) -> None:
        docs: dict[str, _IndexedDoc] = {}
        for entry in await repo.list(""):
            try:
                _, doc = await core.get_document(repo, entry.key)
            except NotFound:
                continue  # listed-then-deleted mid-scan; just skip it
            except Exception:
                # A single malformed/legacy/unmigratable body must not abort the whole
                # scan (it lists with a valid envelope but fails to load) — skip the one
                # doc, mirroring the event path, so every other doc still indexes.
                logger.exception("search index: skipping unreadable doc %r", entry.key)
                continue
            docs[entry.key] = _project(entry.key, doc)
        self._docs = docs

    async def _apply(self, repo: Repository, key: str) -> None:
        try:
            _, doc = await core.get_document(repo, key)
        except NotFound:
            self._docs.pop(key, None)  # deleted -> drop from the index
            return
        # A non-NotFound load error (the run loop catches and logs it) keeps the
        # last-known-good entry rather than evicting: writes flow through the API,
        # which only persists valid docs, so this fires only on a transient fault or
        # out-of-band on-disk corruption — keeping re-syncs on the next write to the
        # key, whereas evicting would drop a good entry on a transient blip.
        self._docs[key] = _project(key, doc)

    def query(self, q: str, *, prefix: str = "") -> SearchResults:
        """Return fuzzy hits over titles and section/phase headings.

        `prefix` scopes to a key prefix (`"alice/demo/"` for one user+project,
        `"alice/"` for one user across projects). The query is split into whitespace
        terms; an entry matches when every term is an in-order subsequence of it, and
        results are ranked by summed match score (best first) with deterministic
        tie-breakers.
        """
        terms = _fold(q).split()
        if not terms:
            return SearchResults(query=q, hits=[])
        # (score, key, kind-order, text) sort tuple paired with its hit; score is
        # negated at sort time so the strongest match leads.
        scored: list[tuple[float, str, int, str, SearchHit]] = []

        def add(score: float, key: str, order: int, text: str, hit: SearchHit) -> None:
            scored.append((score, key, order, text, hit))

        for doc in self._docs.values():
            if not doc.key.startswith(prefix):
                continue
            score = _match(terms, doc.title)
            if score is not None:
                add(
                    score,
                    doc.key,
                    _KIND_ORDER["title"],
                    doc.title,
                    self._hit(doc, kind="title", text=doc.title, anchor=None),
                )
            for heading, anchor in doc.sections:
                score = _match(terms, heading)
                if score is not None:
                    add(
                        score,
                        doc.key,
                        _KIND_ORDER["section"],
                        heading,
                        self._hit(doc, kind="section", text=heading, anchor=anchor),
                    )
            for name, slug in doc.phases:
                score = _match(terms, name)
                if score is not None:
                    add(
                        score,
                        doc.key,
                        _KIND_ORDER["phase"],
                        name,
                        self._hit(doc, kind="phase", text=name, anchor=slug),
                    )
        scored.sort(key=lambda r: (-r[0], r[1], r[2], r[3]))
        return SearchResults(query=q, hits=[r[4] for r in scored])

    @staticmethod
    def _hit(
        doc: _IndexedDoc,
        *,
        kind: Literal["title", "section", "phase"],
        text: str,
        anchor: str | None,
    ) -> SearchHit:
        return SearchHit(
            key=doc.key,
            project=doc.project,
            slug=doc.slug,
            title=doc.title,
            type=doc.doc_type,
            status=doc.status,
            kind=kind,
            text=text,
            anchor=anchor,
        )
