"""Lineage is a pure projection, so these drive it with plain Documents.

They pin each bucket the page renders: primary -> plans, secondary ref -> backlinks,
no/dangling primary -> unlinked, standalone research -> empty node, plus the
deterministic slug ordering the template relies on.
"""

from claudeplans.lineage import build_lineage
from claudeplans_contracts import Document
from claudeplans_contracts.enums import DocType


def _research(slug: str) -> Document:
    return Document(
        type=DocType.research, project="demo", slug=slug, title=slug, owner_id="dev"
    )


def _plan(
    slug: str, refs: list[str] | None = None, primary: str | None = None
) -> Document:
    return Document(
        type=DocType.plan,
        project="demo",
        slug=slug,
        title=slug,
        owner_id="dev",
        research_refs=refs or [],
        primary_research_ref=primary,
    )


def test_primary_ref_nests_plan_under_research() -> None:
    lineage = build_lineage([_research("r1"), _plan("p1", ["r1"], "r1")])
    assert len(lineage.research) == 1
    node = lineage.research[0]
    assert [p.slug for p in node.plans] == ["p1"]
    assert node.backlinks == ()
    assert lineage.unlinked_plans == ()


def test_primary_and_ref_appears_in_plans_not_backlinks() -> None:
    # The plan names r1 as both primary AND a plain ref. Primary wins: it nests under
    # r1.plans and must NOT also show up as a backlink (no double-listing).
    lineage = build_lineage([_research("r1"), _plan("p1", ["r1"], "r1")])
    node = lineage.research[0]
    assert [p.slug for p in node.plans] == ["p1"]
    assert node.backlinks == ()


def test_secondary_ref_is_a_backlink_not_a_plan() -> None:
    # Plan's primary is r2, but it also cites r1 -> r1 lists it as a backlink only.
    lineage = build_lineage(
        [_research("r1"), _research("r2"), _plan("p1", ["r1", "r2"], "r2")]
    )
    by_slug = {n.slug: n for n in lineage.research}
    assert [p.slug for p in by_slug["r1"].backlinks] == ["p1"]
    assert by_slug["r1"].plans == ()
    assert [p.slug for p in by_slug["r2"].plans] == ["p1"]


def test_no_primary_is_unlinked() -> None:
    lineage = build_lineage([_research("r1"), _plan("p1")])
    assert [p.slug for p in lineage.unlinked_plans] == ["p1"]


def test_standalone_research_has_empty_plans() -> None:
    lineage = build_lineage([_research("r1")])
    assert len(lineage.research) == 1
    assert lineage.research[0].plans == ()
    assert lineage.research[0].backlinks == ()


def test_dangling_primary_is_unlinked() -> None:
    # primary points at a research slug that isn't present -> treated as unlinked.
    lineage = build_lineage([_plan("p1", ["ghost"], "ghost")])
    assert lineage.research == ()
    assert [p.slug for p in lineage.unlinked_plans] == ["p1"]


def test_empty_input_is_empty_lineage() -> None:
    lineage = build_lineage([])
    assert lineage.research == ()
    assert lineage.unlinked_plans == ()


def test_deterministic_slug_ordering() -> None:
    lineage = build_lineage(
        [
            _research("rb"),
            _research("ra"),
            _plan("pb", ["ra"], "ra"),
            _plan("pa", ["ra"], "ra"),
        ]
    )
    assert [n.slug for n in lineage.research] == ["ra", "rb"]
    ra = next(n for n in lineage.research if n.slug == "ra")
    assert [p.slug for p in ra.plans] == ["pa", "pb"]
