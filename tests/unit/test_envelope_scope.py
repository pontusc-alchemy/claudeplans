"""Unit tests for envelope scoping (Task 4) and research-ref validation (Task 6)."""

from collections.abc import Iterable
from typing import Any

import pytest

from claudeplans import core
from claudeplans.api.envelope import envelope
from claudeplans.auth.provider import CurrentUser
from claudeplans.storage.repository import ListEntry, Repository, _Create
from claudeplans_contracts import (
    DocStatus,
    DocType,
    Document,
    NotFound,
    Phase,
    PhaseStatus,
    Task,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER = CurrentUser(uid="dev", name="dev", namespace="dev")


def _plan_doc(
    *,
    slug: str = "p1",
    status: DocStatus = DocStatus.active,
    phases: list[Phase] | None = None,
) -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug=slug,
        title="Plan One",
        owner_id="u1",
        status=status,
        phases=phases or [],
    )


def _done_doc_with_open_phase(phase_slug: str) -> Document:
    """A doc marked done with an unchecked task — generates drift on the phase."""
    return _plan_doc(
        status=DocStatus.done,
        phases=[
            Phase(
                slug=phase_slug,
                name="Alpha",
                status=PhaseStatus.done,
                tasks=[Task(text="t1", checked=False)],
            )
        ],
    )


def _make_raw(slug: str, doc_type: DocType) -> dict[str, Any]:
    doc = Document(
        type=doc_type,
        project="demo",
        slug=slug,
        title="T",
        owner_id="dev",
    )
    return doc.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Minimal in-memory repo for Task 6 tests
# ---------------------------------------------------------------------------


class _SimpleRepo(Repository):
    """In-memory repo backed by a pre-loaded dict of raw document dicts."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = dict(docs)
        self._revs = {k: "1" for k in docs}

    async def get(self, key: str) -> tuple[str, dict[str, Any]]:
        if key not in self._docs:
            raise NotFound(key)
        return self._revs[key], self._docs[key]

    async def put(
        self, key: str, document: dict[str, Any], expected_rev: str | _Create
    ) -> str:
        self._docs[key] = document
        self._revs[key] = "2"
        return "2"

    async def delete(self, key: str, expected_rev: str) -> None:
        raise AssertionError("delete not expected")

    async def list(self, prefix: str) -> Iterable[ListEntry]:
        return [
            ListEntry(
                key=k,
                rev=self._revs[k],
                metadata={"type": v.get("type", "")},
            )
            for k, v in self._docs.items()
            if k.startswith(prefix)
        ]


# ---------------------------------------------------------------------------
# Task 4: envelope scope filtering
# ---------------------------------------------------------------------------


def test_envelope_scope_none_returns_all_warnings() -> None:
    # doc=done, phase=done but has open task -> drift on phases.a
    doc = _done_doc_with_open_phase("a")
    result = envelope(doc, scope=None)
    assert len(result.warnings) >= 1
    codes = {w.code for w in result.warnings}
    assert "phase-done-open-tasks" in codes


def test_envelope_scope_matching_phase_keeps_warning() -> None:
    doc = _done_doc_with_open_phase("a")
    result = envelope(doc, scope="phases.a")
    assert any(w.path == "phases.a" for w in result.warnings)


def test_envelope_scope_other_phase_filters_out_phase_warning() -> None:
    # Warning for "a" must be absent when scope is "phases.b".
    doc = _done_doc_with_open_phase("a")
    result = envelope(doc, scope="phases.b")
    phase_warnings = [w for w in result.warnings if w.path is not None]
    for w in phase_warnings:
        path = w.path
        assert path is not None
        assert path == "phases.b" or path.startswith("phases.b.")


def test_envelope_none_path_warnings_survive_any_scope() -> None:
    # path=None warnings are global; they must pass through regardless of scope.
    doc = _done_doc_with_open_phase("a")
    none_path_count = sum(1 for w in envelope(doc).warnings if w.path is None)
    scoped_none_path = sum(
        1 for w in envelope(doc, scope="phases.z").warnings if w.path is None
    )
    assert scoped_none_path == none_path_count


def test_envelope_no_scope_arg_equals_scope_none() -> None:
    doc = _done_doc_with_open_phase("a")
    assert envelope(doc).warnings == envelope(doc, scope=None).warnings


def test_envelope_scope_no_prefix_collision() -> None:
    # scope="phases.a" must NOT match a warning whose path is "phases.ab".
    doc = _done_doc_with_open_phase("ab")
    # scope="phases.a" — warning path is "phases.ab", which is not equal to
    # "phases.a" and does not start with "phases.a." → must be filtered out.
    result_a = envelope(doc, scope="phases.a")
    assert not any(w.path == "phases.ab" for w in result_a.warnings)
    # scope="phases.ab" — exact match → must be included.
    result_ab = envelope(doc, scope="phases.ab")
    assert any(w.path == "phases.ab" for w in result_ab.warnings)


# ---------------------------------------------------------------------------
# Task 6: research-ref validation in core.put_research_refs
# ---------------------------------------------------------------------------


async def test_put_research_refs_rejects_nonexistent_ref() -> None:
    repo = _SimpleRepo({"dev/demo/p1": _make_raw("p1", DocType.plan)})
    with pytest.raises(ValidationError, match="ghost"):
        await core.put_research_refs(repo, "dev/demo/p1", ["ghost"], None, user=_USER)


async def test_put_research_refs_rejects_plan_typed_ref() -> None:
    """A ref that resolves to a plan doc (not research) must be rejected."""
    repo = _SimpleRepo(
        {
            "dev/demo/p1": _make_raw("p1", DocType.plan),
            "dev/demo/p2": _make_raw("p2", DocType.plan),
        }
    )
    with pytest.raises(ValidationError, match="p2"):
        await core.put_research_refs(repo, "dev/demo/p1", ["p2"], None, user=_USER)


async def test_put_research_refs_accepts_research_typed_ref() -> None:
    """A ref resolving to a research doc in the same project succeeds."""
    repo = _SimpleRepo(
        {
            "dev/demo/p1": _make_raw("p1", DocType.plan),
            "dev/demo/r1": _make_raw("r1", DocType.research),
        }
    )
    new_rev, doc = await core.put_research_refs(
        repo, "dev/demo/p1", ["r1"], "r1", user=_USER
    )
    assert new_rev == "2"
    assert doc.research_refs == ["r1"]
    assert doc.primary_parent_ref == "r1"


async def test_put_research_refs_empty_list_succeeds() -> None:
    """An empty ref list is always valid (nothing to resolve)."""
    repo = _SimpleRepo({"dev/demo/p1": _make_raw("p1", DocType.plan)})
    new_rev, doc = await core.put_research_refs(
        repo, "dev/demo/p1", [], None, user=_USER
    )
    assert new_rev == "2"
    assert doc.research_refs == []


# ---------------------------------------------------------------------------
# FIX 4: doc-done-phase-open is document-level (path=None) — survives scoping
# ---------------------------------------------------------------------------


def test_doc_done_phase_open_survives_scope_of_other_phase() -> None:
    # doc=done, phase A=done (but has open task → phase-done-open-tasks on A),
    # phase B=doing → doc-done-phase-open for B.
    # A scoped write to phase A must still surface the doc-level warning about B.
    doc = _plan_doc(
        status=DocStatus.done,
        phases=[
            Phase(
                slug="a",
                name="Alpha",
                status=PhaseStatus.done,
                tasks=[Task(text="t1", checked=True)],
            ),
            Phase(
                slug="b",
                name="Beta",
                status=PhaseStatus.doing,
                tasks=[],
            ),
        ],
    )
    # Scope is phases.a (a write to phase A).
    result = envelope(doc, scope="phases.a")
    # doc-done-phase-open (about phase B, path=None) must be present even though
    # the scope is phases.a — because path=None warnings are never filtered.
    doc_done_warnings = [w for w in result.warnings if w.code == "doc-done-phase-open"]
    assert len(doc_done_warnings) >= 1, (
        "doc-done-phase-open must survive a phases.a scope (it is document-level)"
    )
    # Phase-scoped warnings for phase B must NOT bleed through (scope is phases.a).
    for w in result.warnings:
        if w.path is not None:
            assert w.path == "phases.a" or w.path.startswith("phases.a."), (
                f"unexpected scoped warning {w!r} leaked through scope=phases.a"
            )
